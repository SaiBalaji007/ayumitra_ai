"""
Unit normalisation for lab results.

Only *spelling* variants are unified (gm/dl -> g/dL). Value conversion is applied only where the
factor is exact by definition (e.g. 1 lakh = 100,000), never for molar <-> mass conversions, which
depend on the analyte. The printed unit is always kept alongside.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

CANONICAL = {
    "mg/dl": "mg/dL", "mgs/dl": "mg/dL", "mg%": "mg/dL", "mg / dl": "mg/dL",
    "g/dl": "g/dL", "gm/dl": "g/dL", "gms/dl": "g/dL", "gm%": "g/dL", "g%": "g/dL",
    "mmol/l": "mmol/L", "umol/l": "µmol/L", "µmol/l": "µmol/L", "μmol/l": "µmol/L",
    "ng/ml": "ng/mL", "pg/ml": "pg/mL", "ug/dl": "µg/dL", "µg/dl": "µg/dL", "mcg/dl": "µg/dL",
    "u/l": "U/L", "iu/l": "IU/L", "miu/l": "mIU/L", "uiu/ml": "µIU/mL", "µiu/ml": "µIU/mL", "miu/ml": "mIU/mL",
    "%": "%", "fl": "fL", "pg": "pg", "mm/hr": "mm/h", "mm/h": "mm/h", "mmhg": "mmHg",
    "cells/cumm": "cells/µL", "/cumm": "/µL", "cumm": "/µL", "cells/ul": "cells/µL", "/ul": "/µL",
    "cells/µl": "cells/µL", "10^3/ul": "10^3/µL", "10^3/µl": "10^3/µL", "x10^3/ul": "10^3/µL",
    "thou/ul": "10^3/µL", "10^6/ul": "10^6/µL", "mill/cumm": "10^6/µL", "million/cumm": "10^6/µL",
    "lakhs/cumm": "lakh/µL", "lakh/cumm": "lakh/µL", "lacs/cumm": "lakh/µL", "lakhs/ul": "lakh/µL",
    "meq/l": "mEq/L", "ratio": "ratio",
    "mg/l": "mg/L", "g/l": "g/L", "gm/l": "g/L", "ug/l": "µg/L", "µg/l": "µg/L", "mcg/l": "µg/L", "ng/l": "ng/L",
    "ng/dl": "ng/dL", "ug/ml": "µg/mL", "µg/ml": "µg/mL", "mcg/ml": "µg/mL", "mg/ml": "mg/mL",
    "nmol/l": "nmol/L", "pmol/l": "pmol/L", "mmol/mol": "mmol/mol", "ml/min": "mL/min",
    "ml/min/1.73m2": "mL/min/1.73m²", "ml/min/1.73 m2": "mL/min/1.73m²", "u/ml": "U/mL", "iu/ml": "IU/mL",
    "mu/l": "mU/L", "ku/l": "kU/L", "sec": "s", "secs": "s", "seconds": "s",
    "10^9/l": "10^9/L", "x10^9/l": "10^9/L", "10^12/l": "10^12/L", "x10^12/l": "10^12/L",
}

# Exact definitional factors only: canonical unit -> (target unit, factor)
EXACT_CONVERSIONS = {
    "lakh/µL": ("/µL", Decimal(100000)),
    "10^3/µL": ("/µL", Decimal(1000)),
    "10^6/µL": ("/µL", Decimal(1000000)),
}

UNIT_PATTERN = re.compile(
    r"(?:x\s*)?(?:10\^?\d/(?:u|µ|μ)l|thou/ul|mill(?:ion)?/cumm|lakhs?/(?:cumm|ul)|lacs/cumm|cells/(?:cumm|u?l|µl)|/cumm|"
    r"mgs?/dl|gms?/dl|g/dl|mg%|gm%|g%|mmol/l|[uµμ]mol/l|ng/ml|pg/ml|[uµ]g/dl|mcg/dl|m?iu/l|[uµ]iu/ml|miu/ml|u/l|"
    r"meq/l|mm/hr?|mmhg|fl|pg|%|"
    r"10\^?(?:9|12)/l|ml/min(?:/1\.73\s*m2)?|mmol/mol|[nmp]mol/l|mgs?/l|gms?/l|g/l|[uµμ]g/(?:l|ml)|mcg/(?:l|ml)|"
    r"ng/(?:l|dl)|mg/ml|k?iu/ml|[uµ]/ml|m?u/l|ku/l|sec(?:onds|s)?)",
    re.IGNORECASE,
)


@dataclass
class NormalizedUnit:
    printed: str
    canonical: str | None
    known: bool


def normalize_unit(unit: str) -> NormalizedUnit:
    u = unit.strip()
    key = re.sub(r"\s+", "", u.lower()).replace("μ", "µ").lstrip("x")
    canonical = CANONICAL.get(key)
    return NormalizedUnit(printed=u, canonical=canonical, known=canonical is not None)


def exact_convert(value: Decimal, canonical_unit: str) -> tuple[Decimal, str] | None:
    conv = EXACT_CONVERSIONS.get(canonical_unit)
    if not conv:
        return None
    target, factor = conv
    return value * factor, target
