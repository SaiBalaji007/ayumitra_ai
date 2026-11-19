"""
Medicine name recognition and generic/brand normalisation against RxNorm (U.S. NLM).

Lexicon: RxNorm ingredient (IN) and brand (BN) names from the RxNav API (data/rxnorm/*.json,
fetched by `python -m ayumitra_ai.cli rxnorm`). Brand -> ingredient uses RxNav's related-concept
API and is cached in SQLite.

Safety rules (the point of this module):
- Only an EXACT (case/spacing-insensitive) lexicon match is accepted automatically.
- A fuzzy match is returned only as a *suggestion*: the status says it needs user confirmation,
  and `generic_name` stays empty until the user confirms. "metfromin" is never silently turned
  into anything; RxNav's own approximate search maps it to "merbromin", a different substance.
- Names not in RxNorm (e.g. many Indian brands) are reported as unrecognised, never guessed.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

from ..config import get_settings

RXNAV = "https://rxnav.nlm.nih.gov/REST"

# International Nonproprietary Names (INN, used in India) -> U.S. Adopted Names used by RxNorm.
# Naming conventions only (WHO INN vs USAN), not medical information.
INN_TO_USAN = {
    "paracetamol": "acetaminophen", "salbutamol": "albuterol", "adrenaline": "epinephrine",
    "noradrenaline": "norepinephrine", "frusemide": "furosemide", "lignocaine": "lidocaine",
    "glibenclamide": "glyburide", "pethidine": "meperidine", "rifampicin": "rifampin",
    "cyclosporin": "cyclosporine", "thyroxine": "levothyroxine", "colecalciferol": "cholecalciferol",
}


@dataclass
class MedicineMatch:
    name_as_written: str
    status: str                    # exact_ingredient | exact_brand | suggestion | unrecognized
    generic_name: str = ""         # only for exact matches (brand -> ingredient via RxNorm)
    rxcui: str = ""
    matched_name: str = ""
    score: float = 0.0
    suggestions: list[dict] = field(default_factory=list)
    needs_review: bool = True
    source: str = "RxNorm (U.S. National Library of Medicine)"

    def to_dict(self):
        return asdict(self)


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


class RxNormLexicon:
    def __init__(self, data_dir: Path | None = None, *, online: bool = True):
        self.dir = Path(data_dir or get_settings().data_dir / "rxnorm")
        self.online = online
        self.ingredients: dict[str, tuple[str, str]] = {}  # key -> (rxcui, name)
        self.brands: dict[str, tuple[str, str]] = {}
        for tty, target in (("in", self.ingredients), ("bn", self.brands)):
            p = self.dir / f"{tty}.json"
            if p.exists():
                for c in json.loads(p.read_text(encoding="utf-8"))["concepts"]:
                    target.setdefault(_key(c["name"]), (c["rxcui"], c["name"]))
        self._by_first = {}
        for k in list(self.ingredients) + list(self.brands):
            self._by_first.setdefault(k[:1], []).append(k)
        self._cache_path = self.dir / "brand_ingredients.sqlite3"

    @property
    def loaded(self) -> bool:
        return bool(self.ingredients)

    # --- brand -> ingredient (cached RxNav lookup) ---
    def _cache(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._cache_path)
        conn.execute("CREATE TABLE IF NOT EXISTS brand_in (rxcui TEXT PRIMARY KEY, ingredients TEXT NOT NULL)")
        return conn

    def ingredients_of_brand(self, rxcui: str) -> list[str]:
        with self._cache() as conn:
            row = conn.execute("SELECT ingredients FROM brand_in WHERE rxcui = ?", (rxcui,)).fetchone()
            if row:
                return json.loads(row[0])
            if not self.online:
                return []
            import httpx

            try:
                r = httpx.get(f"{RXNAV}/rxcui/{rxcui}/related.json", params={"tty": "IN"}, timeout=20)
                r.raise_for_status()
                groups = r.json().get("relatedGroup", {}).get("conceptGroup", [])
                names = sorted({p["name"] for g in groups for p in g.get("conceptProperties", [])})
            except Exception:
                return []  # unknown is reported as unknown; never guessed
            conn.execute("INSERT OR REPLACE INTO brand_in VALUES (?, ?)", (rxcui, json.dumps(names)))
            return names

    # --- matching ---
    def _fuzzy(self, key: str, limit: int = 3) -> list[tuple[float, str]]:
        pool = self._by_first.get(key[:1], [])
        scored = []
        for cand in pool:
            if abs(len(cand) - len(key)) > 3:
                continue
            s = SequenceMatcher(None, key, cand).ratio()
            if s >= 0.8:
                scored.append((s, cand))
        scored.sort(reverse=True)
        return scored[:limit]

    def match(self, name: str) -> MedicineMatch:
        key = _key(name)
        if not key:
            return MedicineMatch(name, "unrecognized")
        if key in INN_TO_USAN and INN_TO_USAN[key] in self.ingredients:
            rxcui, canon = self.ingredients[INN_TO_USAN[key]]
            return MedicineMatch(name, "exact_ingredient", generic_name=canon.lower(), rxcui=rxcui,
                                 matched_name=f"{canon} (INN: {key})", score=1.0, needs_review=False)
        if key in self.ingredients:
            rxcui, canon = self.ingredients[key]
            return MedicineMatch(name, "exact_ingredient", generic_name=canon.lower(), rxcui=rxcui, matched_name=canon,
                                 score=1.0, needs_review=False)
        if key in self.brands:
            rxcui, canon = self.brands[key]
            ings = self.ingredients_of_brand(rxcui)
            return MedicineMatch(name, "exact_brand", generic_name=" / ".join(ings), rxcui=rxcui, matched_name=canon,
                                 score=1.0, needs_review=not ings)
        # Indian brands (not in RxNorm): recognised, but the user must confirm before it is used.
        indian = default_indian_brands()
        if row := indian.exact(name):
            sug = indian_brand_suggestion(row, 1.0)
            return MedicineMatch(name, "indian_brand", matched_name=row["brand"], score=1.0, suggestions=[sug],
                                 source="AyuMitra list of common Indian brands")
        suggestions = [indian_brand_suggestion(row, s) for s, row in indian.fuzzy(name)]
        for score, cand in self._fuzzy(key):
            rxcui, canon = self.ingredients.get(cand) or self.brands.get(cand)
            kind = "ingredient" if cand in self.ingredients else "brand"
            suggestions.append({"name": canon, "rxcui": rxcui, "kind": kind, "similarity": round(score, 3)})
        if suggestions:
            suggestions.sort(key=lambda s: -s["similarity"])
            return MedicineMatch(name, "suggestion", score=suggestions[0]["similarity"], suggestions=suggestions[:3])
        return MedicineMatch(name, "unrecognized")


INDIAN_BRANDS_PATH = Path(__file__).resolve().parent.parent.parent / "knowledge" / "indian_brands.json"
_STRENGTH_TAIL = re.compile(r"(\s+(\d+(\.\d+)?\s*(k|mg|mcg|g|ml|iu)?|forte|plus|sr|er|xr|od|ds))+$")


class IndianBrands:
    """Common Indian brand names -> generic ingredients (knowledge/indian_brands.json).

    RxNorm is a U.S. database and lacks most Indian brands. A hit here is never applied automatically:
    it is offered as a suggestion ("Shelcal = calcium carbonate + vitamin D3, please confirm")."""

    def __init__(self, path: Path = INDIAN_BRANDS_PATH):
        rows = json.loads(path.read_text(encoding="utf-8"))["brands"] if path.exists() else []
        self.by_key = {_key(r["brand"]): r for r in rows}

    def _candidates(self, key: str) -> list[str]:
        """'shelcal 500' -> ['shelcal 500', 'shelcal']; 'd3 must 60k' -> [..., 'd3 must']."""
        out = [key]
        stripped = _STRENGTH_TAIL.sub("", key).strip()
        if stripped and stripped != key:
            out.append(stripped)
        return out

    def exact(self, name: str) -> dict | None:
        for cand in self._candidates(_key(name)):
            if cand in self.by_key:
                return self.by_key[cand]
        return None

    def fuzzy(self, name: str, threshold: float = 0.78, limit: int = 2) -> list[tuple[float, dict]]:
        """Close spellings ('helcal' -> Shelcal), for handwriting/OCR misreads. Suggestions only."""
        scored = {}
        for cand in self._candidates(_key(name)):
            for bkey, row in self.by_key.items():
                if abs(len(bkey) - len(cand)) > 3:
                    continue
                s = SequenceMatcher(None, cand, bkey).ratio()
                if s >= threshold and s > scored.get(bkey, (0,))[0]:
                    scored[bkey] = (s, row)
        return sorted(scored.values(), key=lambda x: -x[0])[:limit]


def indian_brand_suggestion(row: dict, similarity: float) -> dict:
    generic = " + ".join(row["generic"])
    return {"name": f"{row['brand']} ({generic})", "generic": generic, "rxcui": "", "kind": "indian_brand",
            "similarity": round(similarity, 3), "source": "AyuMitra list of common Indian brands"}


@lru_cache(maxsize=1)
def default_indian_brands() -> IndianBrands:
    return IndianBrands()


@lru_cache(maxsize=1)
def default_lexicon() -> RxNormLexicon:
    return RxNormLexicon()


def download_lexicon(data_dir: Path | None = None) -> dict[str, int]:
    """Fetch RxNorm ingredient and brand names from RxNav (public, no key)."""
    import httpx

    out = Path(data_dir or get_settings().data_dir / "rxnorm")
    out.mkdir(parents=True, exist_ok=True)
    counts = {}
    for tty in ("IN", "BN"):
        r = httpx.get(f"{RXNAV}/allconcepts.json", params={"tty": tty}, timeout=180)
        r.raise_for_status()
        rows = [{"rxcui": c["rxcui"], "name": c["name"]} for c in r.json()["minConceptGroup"]["minConcept"]
                if len(c["name"]) <= 60]
        (out / f"{tty.lower()}.json").write_text(json.dumps({"source": "RxNorm via RxNav allconcepts API (U.S. NLM)",
                                                             "tty": tty, "concepts": rows}), encoding="utf-8")
        counts[tty] = len(rows)
    return counts
