import logging
import random
import re
from datetime import date, datetime
from functools import lru_cache
from typing import List

import requests
from bs4 import BeautifulSoup
from waste_collection_schedule import Collection  # type: ignore[attr-defined]
from waste_collection_schedule.exceptions import (
    SourceArgAmbiguousWithSuggestions,
    SourceArgumentNotFoundWithSuggestions,
    SourceArgumentRequired,
)

TITLE = "Affaldonline"
DESCRIPTION = "Affaldonline"
URL = "https://affaldonline.dk"
BASE_URL = "https://www.affaldonline.dk/kalender/{municipality}"
API_URL = "https://www.affaldonline.dk/kalender/{municipality}/showInfo.php"

_LOGGER = logging.getLogger("waste_collection_schedule.affaldonline_dk")

PARSERS = {
    "default": {
        "description": "Næste tømningsdag: DD den D MMMMM YYYY (waste_type_1, waste_type_2)",
        "regex": r"(\d{1,2})\. (\w+) (\d{4})",
        "enabled": True,
    },
    "silkeborg": {
        "description": "A table with dates in the format DD-MM and waste types",
        "regex": r"(\d{2})-(\d{2})",
        "enabled": True,
    },
    "favrskov": {
        "description": "Blåmejsevej 1 (8382 Hinnerup) with multiple waste types",
        "regex": r"Næste tømningsdag: (\w+) den (\d{1,2})\. (\w+) (\d{4})",
        "enabled": True,
    },
    "pdf": {
        "description": "Not yet supported parser for PDF files",
        "regex": None,
        "enabled": False,
    },
}

AFFALDONLINE_MUNICIPALITIES = {
    "aeroe": {
        "title": "Ærø Kommune",
        "url": "https://www.aeroekommune.dk/",
        "parser": "default",
        "values": "Nørregade|1||||5970|Ærøskøbing|1228262|448776|0",
    },
    "assens": {
        "title": "Assens Forsyning",
        "url": "https://www.assensforsyning.dk/",
        "parser": "default",
        "values": "Nørregade|1||||5610|Assens|10894|430000|0",
    },
    "favrskov": {
        "title": "Favrskov Forsyning",
        "url": "https://www.favrskovforsyning.dk",
        "parser": "favrskov",
        "values": "Nørregade|1||||8382|Hinnerup|6443|108156|0",
    },
    "fanoe": {
        "title": "Fanø Kommune",
        "url": "https://fanoe.dk/",
        "parser": "pdf",
        "values": "Nørre Klit|5||||6720|Fanø|2582|1747246|0",
    },
    "ffv": {
        "title": "Faaborg Forsynings Virksomhed",
        "url": "https://www.ffv.dk/",
        "parser": "pdf",
        "values": "Marsk Billesvej|18||||5672|Broby|36193544|576846|0",
    },
    "fredericia": {
        "title": "Fredericia Kommune Affald & Genbrug",
        "url": "https://affaldgenbrug-fredericia.dk/",
        "parser": "pdf",
        "values": "Nørre Allé|5||||7000|Fredericia|11079971|1907927|0",
    },
    "holbaek": {
        "title": "Fors A/S (Holbæk Kommune)",
        "url": "https://www.fors.dk/affald/afhentning-af-affald/",
        "parser": "default",
        "values": "Tåstrup Møllevej|5||||4300|Holbæk|76490500|1676484|0",
    },
    "langeland": {
        "title": "Langeland Forsyning",
        "url": "https://www.langeland-forsyning.dk/",
        "parser": "default",
        "values": "Nørregade|1||||5900|Rudkøbing|3535|383566|0",
    },
    "middelfart": {
        "title": "Middelfart Kommune",
        "url": "https://middelfart.dk/",
        "parser": "default",
        "values": "Nørregade|2||||5592|Ejby|11288085|6496420|0",
    },
    "nyborg": {
        "title": "Nyborg Forsyning & Service A/S",
        "url": "https://www.nfs.as/",
        "parser": "pdf",
        "values": "Nørregade|5||||5800|Nyborg|8896288|552542|0",
    },
    "rebild": {
        "title": "Rebild Kommune",
        "url": "https://rebild.dk/",
        "parser": "default",
        "values": "Nørregade|1||||9500|Hobro|4676913|1012588|0",
    },
    "silkeborg": {
        "title": "Silkeborg Forsyning",
        "url": "https://www.silkeborgforsyning.dk/",
        "parser": "silkeborg",
        "values": "Nørregade|5||||8620|Kjellerup|45814316|1291964|0",
    },
    "soroe": {
        "title": "Sorø Kommune",
        "url": "https://soroe.dk/",
        "parser": "pdf",
        "values": "Nørrevej|4| |||4180|Sorø|8569|8838|0|0",
    },
    "vejle": {
        "title": "Vejle Kommune",
        "url": "https://www.vejle.dk/",
        "parser": "default",
        "values": "Nørregade|69||||7100|Vejle|16285351|16285351|0",
    },
}

EXTRA_INFO = [
    {
        "title": info["title"],
        "url": info["url"],
        "default_params": {"municipality": municipality},
    }
    for municipality, info in AFFALDONLINE_MUNICIPALITIES.items()
    if info["parser"] != "pdf"
]


def select_test_cases(municipalities, mode="random_one_from_each_parser"):
    test_cases = {}
    parser_test_cases = {}

    for name, info in municipalities.items():
        parser = info["parser"]
        if PARSERS[parser]["enabled"]:
            if parser not in parser_test_cases:
                parser_test_cases[parser] = []
            parser_test_cases[parser].append((name, info))

    if mode == "random_one_from_each_parser":
        for parser, cases in parser_test_cases.items():
            selected_case = random.choice(cases)
            test_cases[selected_case[0]] = {
                "municipality": selected_case[0],
                "values": selected_case[1]["values"],
            }
    elif mode == "first_from_each_parser":
        for parser, cases in parser_test_cases.items():
            selected_case = cases[0]
            test_cases[selected_case[0]] = {
                "municipality": selected_case[0],
                "values": selected_case[1]["values"],
            }
    elif mode == "random_one":
        all_cases = [case for cases in parser_test_cases.values() for case in cases]
        selected_case = random.choice(all_cases)
        test_cases[selected_case[0]] = {
            "municipality": selected_case[0],
            "values": selected_case[1]["values"],
        }
    elif mode == "first_one":
        first_parser = list(parser_test_cases.keys())[0]
        selected_case = parser_test_cases[first_parser][0]
        test_cases[selected_case[0]] = {
            "municipality": selected_case[0],
            "values": selected_case[1]["values"],
        }
    elif mode == "all":
        for parser, cases in parser_test_cases.items():
            for case in cases:
                test_cases[case[0]] = {
                    "municipality": case[0],
                    "values": case[1]["values"],
                }

    return test_cases


# Dynamically generate TEST_CASES from the AFFALDONLINE_MUNICIPALITIES dictionary
TEST_CASES = select_test_cases(
    AFFALDONLINE_MUNICIPALITIES, mode="first_from_each_parser"
)

PARAM_TRANSLATIONS = {
    "en": {
        "municipality": "Municipality",
        "values": "Advanced values string",
        "street": "Street",
        "house_number": "House number",
        "postal_code": "Postal code",
        "city": "City",
    },
}

PARAM_DESCRIPTIONS = {
    "en": {
        "municipality": "AffaldOnline municipality key, for example 'holbaek'.",
        "values": (
            "Optional advanced AffaldOnline values string. If set, street and house "
            "number lookup is skipped."
        ),
        "street": "Street name. Required when values is not set.",
        "house_number": (
            "House number, including letter/floor/door if shown. Spaces are optional "
            "for compound labels. Required when values is not set."
        ),
        "postal_code": "Postal code. Recommended when a street name exists in multiple cities.",
        "city": (
            "City or postal district. Recommended when a street name exists in multiple "
            "cities; postal-code matches are still used if AffaldOnline has another "
            "district label."
        ),
    },
}

HOW_TO_GET_ARGUMENTS_DESCRIPTION = {
    "en": (
        "Use street, house_number, and preferably postal_code/city. The source will "
        "resolve the internal AffaldOnline values string automatically."
    ),
}

DANISH_MONTHS = [
    "januar",
    "februar",
    "marts",
    "april",
    "maj",
    "juni",
    "juli",
    "august",
    "september",
    "oktober",
    "november",
    "december",
]


def _clean_optional(value: str | int | None) -> str | None:
    if value is None:
        return None

    return str(value).strip()


def _display_street_suggestion(street: dict) -> str:
    return str(
        street.get("value")
        or f"{street.get('vejnavn', '')} ({street.get('postnr', '')} {street.get('Bynavn', '')})"
    )


def _normalize_house_number_label(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


@lru_cache(maxsize=256)
def _resolve_values(
    municipality: str,
    street: str,
    house_number: str,
    postal_code: str | None,
    city: str | None,
) -> str:
    base_url = BASE_URL.format(municipality=municipality)
    street_response = requests.get(f"{base_url}/acCal.php", params={"term": street})
    street_response.raise_for_status()

    street_candidates = street_response.json() or []
    matching_streets = []
    suggestions = []

    for candidate in street_candidates:
        if not isinstance(candidate, dict):
            continue

        suggestion = _display_street_suggestion(candidate)
        suggestions.append(suggestion)

        candidate_street = str(candidate.get("vejnavn", "")).casefold()

        if candidate_street == street.casefold():
            matching_streets.append(candidate)

    if not matching_streets:
        raise SourceArgumentNotFoundWithSuggestions("street", street, suggestions)

    if postal_code is not None:
        matching_streets = [
            candidate
            for candidate in matching_streets
            if str(candidate.get("postnr", "")).strip() == postal_code
        ]

        if not matching_streets:
            raise SourceArgumentNotFoundWithSuggestions("street", street, suggestions)

    if city is not None:
        city_matches = [
            candidate
            for candidate in matching_streets
            if str(candidate.get("Bynavn", "")).casefold() == city.casefold()
        ]

        if city_matches:
            matching_streets = city_matches

    if len(matching_streets) > 1:
        raise SourceArgAmbiguousWithSuggestions(
            "street", street, [_display_street_suggestion(s) for s in matching_streets]
        )

    selected_street = matching_streets[0]
    house_response = requests.get(
        f"{base_url}/husnrCal.php",
        params={
            "vejnavn": selected_street["vejnavn"],
            "postnr": selected_street["postnr"],
            "postdist": selected_street["Bynavn"],
        },
    )
    house_response.raise_for_status()

    soup = BeautifulSoup(house_response.text, "html.parser")
    house_options = soup.find_all("option")
    house_suggestions = [option.get_text(strip=True) for option in house_options]
    normalized_house_number = _normalize_house_number_label(house_number)

    for option in house_options:
        option_text = option.get_text(strip=True)
        if (
            option_text.casefold() == house_number.casefold()
            or _normalize_house_number_label(option_text) == normalized_house_number
        ):
            return option["value"]

    raise SourceArgumentNotFoundWithSuggestions(
        "house_number", house_number, house_suggestions
    )


class Source:
    def __init__(
        self,
        municipality: str,
        values: str | None = None,
        street: str | None = None,
        house_number: str | int | None = None,
        postal_code: str | int | None = None,
        city: str | None = None,
    ):
        _LOGGER.debug(
            "Initializing Source with municipality=%s, values=%s, street=%s, house_number=%s, postal_code=%s, city=%s",
            municipality,
            values,
            street,
            house_number,
            postal_code,
            city,
        )
        self._api_url = API_URL.format(municipality=municipality)
        self._parser_type = AFFALDONLINE_MUNICIPALITIES.get(municipality, {}).get(
            "parser"
        )
        if not self._parser_type:
            raise SourceArgumentNotFoundWithSuggestions(
                "municipality", municipality, AFFALDONLINE_MUNICIPALITIES.keys()
            )

        parser = getattr(self, f"_parse_{self._parser_type}", None)
        if parser is None:
            raise ValueError(f"Parser method for {self._parser_type} not implemented")
        if not callable(parser):
            raise ValueError(f"Parser method for {self._parser_type} is not callable")

        street = _clean_optional(street)
        house_number = _clean_optional(house_number)
        postal_code = _clean_optional(postal_code)
        city = _clean_optional(city)

        if values is None:
            if street is None:
                raise SourceArgumentRequired(
                    "street", "provide either values or street + house_number"
                )
            if house_number is None:
                raise SourceArgumentRequired(
                    "house_number", "provide either values or street + house_number"
                )

            values = _resolve_values(
                municipality, street, house_number, postal_code, city
            )

        self._values = values
        self._parser_method = parser

    def fetch(self) -> List[Collection]:
        _LOGGER.debug("Fetching data from %s", self._api_url)

        entries: List[Collection] = []

        post_data = {"values": self._values}

        response = requests.post(self._api_url, data=post_data)
        response.raise_for_status()

        html_content = response.text
        soup = BeautifulSoup(html_content, "html.parser")

        entries.extend(self._parser_method(soup))

        return entries

    def _parse_default(self, soup: BeautifulSoup) -> List[Collection]:
        entries: List[Collection] = []

        next_pickup_info = soup.find_all(string=re.compile("Næste tømningsdag:"))
        if not next_pickup_info:
            raise ValueError(
                "No waste schemes found. Please check the provided values."
            )

        for info in next_pickup_info:
            text = info.strip()
            match = re.search(r"(\d{1,2})\. (\w+) (\d{4})", text)
            if match:
                try:
                    day = int(match.group(1))
                    month_name = match.group(2)
                    year = int(match.group(3))
                    month_index = DANISH_MONTHS.index(month_name) + 1
                    formatted_date = date(year, month_index, day)

                    # Extract waste types from the text
                    waste_type_search = re.search(r"\((.*?)\)", text)
                    if waste_type_search is None:
                        _LOGGER.warning("No waste type found in string: %s", text)
                        continue
                    waste_types_text = waste_type_search.group(1)

                    waste_types = [
                        waste_type.strip() for waste_type in waste_types_text.split(",")
                    ]

                    for waste_type in waste_types:
                        entries.append(Collection(date=formatted_date, t=waste_type))
                        _LOGGER.debug(
                            "Added collection: date=%s, type=%s",
                            formatted_date,
                            waste_type,
                        )
                except ValueError as e:
                    _LOGGER.error("Error parsing date: %s from string: %s", e, text)
            else:
                _LOGGER.warning("No valid date found in string: %s", text)

        return entries

    def _parse_silkeborg(self, soup: BeautifulSoup) -> List[Collection]:
        entries: List[Collection] = []

        table = soup.find("table")
        if not table:
            raise ValueError(
                "No waste collection table found. Please check the provided values."
            )

        current_year = datetime.now().year
        current_month = datetime.now().month

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) == 2:
                # Extract date and waste type
                date_str = cells[0].get_text(strip=True)
                waste_types = cells[1].get_text(strip=True)

                match = re.search(r"(\d{2})-(\d{2})", date_str)
                if match:
                    day = int(match.group(1))
                    month = int(match.group(2))

                    # Determine the year based on the current month
                    collection_year = current_year
                    if month < current_month:
                        collection_year += 1

                    collection_date = date(collection_year, month, day)

                    for waste_type in waste_types.split(","):
                        entries.append(
                            Collection(date=collection_date, t=waste_type.strip())
                        )
                        _LOGGER.debug(
                            "Added collection: date=%s, type=%s",
                            collection_date,
                            waste_type.strip(),
                        )

        return entries

    def _parse_favrskov(self, soup: BeautifulSoup) -> List[Collection]:
        entries: List[Collection] = []

        strong_tags = soup.find_all("strong")
        if not strong_tags:
            raise ValueError(
                "No waste schemes found. Please check the provided values."
            )

        for strong_tag in strong_tags:
            waste_type = strong_tag.get_text(strip=True)
            next_sibling = strong_tag.find_next_sibling(text=True)
            if next_sibling and "Næste tømningsdag" in next_sibling:
                match = re.search(r"(\d{1,2})\. (\w+) (\d{4})", next_sibling)
                if match:
                    try:
                        day = int(match.group(1))
                        month_name = match.group(2)
                        year = int(match.group(3))
                        month_index = DANISH_MONTHS.index(month_name) + 1
                        formatted_date = date(year, month_index, day)

                        entries.append(Collection(date=formatted_date, t=waste_type))
                        _LOGGER.debug(
                            "Added collection: date=%s, type=%s",
                            formatted_date,
                            waste_type,
                        )
                    except ValueError as e:
                        _LOGGER.error(
                            "Error parsing date: %s from string: %s", e, next_sibling
                        )
                else:
                    _LOGGER.warning("No valid date found in string: %s", next_sibling)

        return entries
