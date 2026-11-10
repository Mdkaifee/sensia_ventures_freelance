"""Literal field normalization; no fuzzy matching or inferred corrections."""

import re
from dataclasses import dataclass
from typing import Mapping


def text(value: object) -> str:
    return "" if value is None else str(value)


def name(value: object) -> str:
    return re.sub(r"[^A-Z]", "", text(value).upper())


def zip5(value: object) -> str | None:
    # Excel numeric cells may arrive as integral floats; never truncate decimals.
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    part = text(value).split("-", 1)[0].strip()
    return part.zfill(5) if re.fullmatch(r"[0-9]{3,5}", part) else None


def address(value: object, suffixes: Mapping[str, str]) -> tuple[str, str]:
    tokens = text(value).upper().replace(".", " ").replace(",", " ").split()
    if not tokens or not re.fullmatch(r"[0-9]+", tokens[0]):
        return "", ""
    house, *street = tokens
    if street:
        street[-1] = suffixes.get(street[-1], street[-1])
    return house, " ".join(street)


def unit(value: object) -> str:
    cleaned = text(value).upper().translate(str.maketrans("", "", ".,#"))
    return "".join(t for t in cleaned.split() if t not in {"APT", "APARTMENT", "UNIT", "STE", "SUITE"})


@dataclass(frozen=True)
class Identity:
    first: str
    last: str
    suffix: str
    postal: str | None
    house: str
    street: str
    apartment: str

    @property
    def valid(self) -> bool:
        return bool(self.last and self.postal and self.house)

    @property
    def block(self) -> tuple:
        return self.postal, self.house, self.street, self.apartment, self.last


def normalize(row: Mapping[str, object], suffixes: Mapping[str, str]) -> Identity:
    house, street = address(row["ADDRESS_1"], suffixes)
    return Identity(name(row["FIRST_NAME"]), name(row["LAST_NAME"]), name(row["SUFFIX"]),
                    zip5(row["ZIP"]), house, street, unit(row["ADDRESS_2"]))
