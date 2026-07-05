import calendar as _stdlib_calendar  # noqa: F401
import os
import sys
from datetime import date

sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "custom_components",
            "waste_collection_schedule",
        )
    ),
)

from waste_collection_schedule.source import affaldonline_dk  # noqa: E402


class MockResponse:
    def __init__(self, text="", json_data=None, status_code=200):
        self.text = text
        self._json_data = json_data
        self.status_code = status_code

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise affaldonline_dk.requests.HTTPError()


def test_resolves_address_fields_to_affaldonline_values(monkeypatch):
    if hasattr(affaldonline_dk, "_resolve_values"):
        affaldonline_dk._resolve_values.cache_clear()

    street_response = MockResponse(
        json_data=[
            {
                "value": "Lookupvej (1000 Otherby)",
                "vejnavn": "Lookupvej",
                "postnr": "1000",
                "Bynavn": "Otherby",
            },
            {
                "value": "Lookupvej (1234 Lookupby)",
                "vejnavn": "Lookupvej",
                "postnr": "1234",
                "Bynavn": "Lookupby",
            },
        ]
    )
    house_response = MockResponse(
        text="""
        <select id="SelHusNr" name="values">
            <option value="Lookupvej|11||||1234|Lookupby|100|200|0">11</option>
            <option value="Lookupvej|12||||1234|Lookupby|101|201|0">12</option>
        </select>
        """
    )
    schedule_response = MockResponse(
        text="Næste tømningsdag: mandag den 6. juli 2026 (Rest/Mad, Pap/Papir)"
    )
    get_responses = [street_response, house_response]
    get_calls = []
    posted_data = []

    def mock_get(url, params):
        get_calls.append((url, params))
        assert url in {
            "https://www.affaldonline.dk/kalender/holbaek/acCal.php",
            "https://www.affaldonline.dk/kalender/holbaek/husnrCal.php",
        }
        return get_responses.pop(0)

    def mock_post(url, data):
        posted_data.append(data)
        return schedule_response

    monkeypatch.setattr(affaldonline_dk.requests, "get", mock_get)
    monkeypatch.setattr(affaldonline_dk.requests, "post", mock_post)

    source_kwargs = {
        "municipality": "holbaek",
        "street": "Lookupvej",
        "house_number": "12",
        "postal_code": "1234",
        "city": "Lookupby",
    }
    source = affaldonline_dk.Source(**source_kwargs)
    cached_source = affaldonline_dk.Source(**source_kwargs)

    entries = source.fetch()
    cached_source.fetch()

    assert len(get_calls) == 2
    assert posted_data == [
        {"values": "Lookupvej|12||||1234|Lookupby|101|201|0"},
        {"values": "Lookupvej|12||||1234|Lookupby|101|201|0"},
    ]
    assert [(entry.date, entry.type) for entry in entries] == [
        (date(2026, 7, 6), "Rest/Mad"),
        (date(2026, 7, 6), "Pap/Papir"),
    ]


def test_resolves_compact_compound_house_number(monkeypatch):
    if hasattr(affaldonline_dk, "_resolve_values"):
        affaldonline_dk._resolve_values.cache_clear()

    def mock_get(url, params):
        if url.endswith("/acCal.php"):
            return MockResponse(
                json_data=[
                    {
                        "value": "Compoundvej (2345 Actualby)",
                        "vejnavn": "Compoundvej",
                        "postnr": "2345",
                        "Bynavn": "Actualby",
                    }
                ]
            )

        assert params == {
            "vejnavn": "Compoundvej",
            "postnr": "2345",
            "postdist": "Actualby",
        }
        return MockResponse(
            text="""
            <select id="SelHusNr" name="values">
                <option value="Compoundvej|11||ST|TV|2345|Actualby|300|400|695">11 ST TV</option>
                <option value="Compoundvej|37|A||i|2345|Actualby|301|401|0">37 A i</option>
            </select>
            """
        )

    monkeypatch.setattr(affaldonline_dk.requests, "get", mock_get)

    source = affaldonline_dk.Source(
        municipality="holbaek",
        street="Compoundvej",
        house_number="37Ai",
        postal_code="2345",
        city="Aliasby",
    )

    assert source._values == "Compoundvej|37|A||i|2345|Actualby|301|401|0"


def test_blank_values_field_still_uses_address_resolution(monkeypatch):
    if hasattr(affaldonline_dk, "_resolve_values"):
        affaldonline_dk._resolve_values.cache_clear()

    def mock_get(url, params):
        if url.endswith("/acCal.php"):
            return MockResponse(
                json_data=[
                    {
                        "value": "Blankvej (3456 Emptyby)",
                        "vejnavn": "Blankvej",
                        "postnr": "3456",
                        "Bynavn": "Emptyby",
                    }
                ]
            )

        assert params == {
            "vejnavn": "Blankvej",
            "postnr": "3456",
            "postdist": "Emptyby",
        }
        return MockResponse(
            text="""
            <select id="SelHusNr" name="values">
                <option value="Blankvej|7||||3456|Emptyby|500|600|0">7</option>
            </select>
            """
        )

    monkeypatch.setattr(affaldonline_dk.requests, "get", mock_get)

    source = affaldonline_dk.Source(
        municipality="holbaek",
        values=" ",
        street=" Blankvej ",
        house_number=" 7 ",
        postal_code="3456",
    )

    assert source._values == "Blankvej|7||||3456|Emptyby|500|600|0"
