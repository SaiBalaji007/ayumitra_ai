"""Text normalisation, sentence splitting with offsets, tokenisation and number extraction."""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------

_WS = re.compile(r"[ \t  -​  　]+")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_MULTI_NL = re.compile(r"\n{3,}")


def normalize_unicode(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    replacements = {
        "‘": "'", "’": "'", "“": '"', "”": '"',
        "–": "-", "—": " - ", "−": "-", "­": "", "﻿": "",
    }
    for a, b in replacements.items():
        text = text.replace(a, b)
    return text


def clean_text(text: str) -> str:
    """Unicode normalisation, de-hyphenation of line breaks, whitespace collapsing."""
    text = normalize_unicode(text)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _MULTI_NL.sub("\n\n", text).strip()


# ---------------------------------------------------------------------------
# Sentences (with character offsets, so citations can quote source text exactly)
# ---------------------------------------------------------------------------

_ABBREVIATIONS = {
    "e.g", "i.e", "etc", "vs", "dr", "mr", "mrs", "ms", "prof", "no", "fig", "approx", "dept",
    "mg", "mcg", "ml", "dl", "mmol", "u.s", "jan", "feb", "mar", "apr", "jun", "jul", "aug",
    "sep", "sept", "oct", "nov", "dec", "st", "al",
}
_SENT_END = re.compile(r"[.!?](?=[\"')\]]*\s+|[\"')\]]*$)")


def split_sentences(text: str) -> list[tuple[str, int, int]]:
    """Split into sentences; returns (sentence, start, end) offsets into `text`.

    Line breaks between list items/paragraphs also end a sentence. Decimal numbers ("5.7")
    and common abbreviations ("e.g.", "mg.") do not.
    """
    spans: list[tuple[int, int]] = []
    for block in re.finditer(r"[^\n]+", text):
        b_start = block.start()
        seg = block.group(0)
        start = 0
        for m in _SENT_END.finditer(seg):
            end = m.end()
            before = seg[start:m.start()]
            last_word = re.split(r"\s+", before.strip())[-1].lower() if before.strip() else ""
            if last_word.rstrip(".") in _ABBREVIATIONS or re.fullmatch(r"[a-z]", last_word):
                continue
            nxt = seg[end:].lstrip()
            if nxt and nxt[0].islower():  # "approx. half" style continuation
                continue
            spans.append((b_start + start, b_start + end))
            start = end
        if seg[start:].strip():
            spans.append((b_start + start, b_start + len(seg)))

    out = []
    for s, e in spans:
        raw = text[s:e]
        lead = len(raw) - len(raw.lstrip())
        trail = len(raw) - len(raw.rstrip())
        s2, e2 = s + lead, e - trail
        if e2 > s2:
            out.append((text[s2:e2], s2, e2))
    return out


def word_count(text: str) -> int:
    return len(text.split())


# ---------------------------------------------------------------------------
# Tokenisation for BM25 and lexical checks
# ---------------------------------------------------------------------------

STOPWORDS = frozenset(
    """a about above after again against all am an and any are as at be because been before being below
    between both but by can could did do does doing down during each few for from further had has have
    having he her here hers herself him himself his how i if in into is it its itself just me more most my
    myself no nor not now of off on once only or other our ours ourselves out over own same she should so
    some such than that the their theirs them themselves then there these they this those through to too
    under until up very was we were what when where which while who whom why will with would you your
    yours yourself yourselves also may might must shall s t don dont doesn isn aren wasn weren""".split()
)

# Keep medical tokens intact: "hba1c", "ldl-c", "vitamin-d", "mg/dl", "25-hydroxy".
_TOKEN = re.compile(r"[a-z0-9]+(?:[-/][a-z0-9]+)*")


def stem(token: str) -> str:
    """Very light suffix stripping. Conservative on purpose: medical words are easy to break."""
    if len(token) <= 4 or any(c.isdigit() for c in token):
        return token
    for suffix, repl in (("ies", "y"), ("sses", "ss"), ("ness", ""), ("ing", ""), ("ed", ""), ("es", "e"), ("s", "")):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            if suffix == "s" and token.endswith(("ss", "us", "is")):
                return token
            return token[: len(token) - len(suffix)] + repl
    return token


def tokenize(text: str, *, keep_stopwords: bool = False) -> list[str]:
    text = normalize_unicode(text).lower()
    tokens = []
    for tok in _TOKEN.findall(text):
        if not keep_stopwords and tok in STOPWORDS:
            continue
        tokens.append(stem(tok))
        if "-" in tok or "/" in tok:  # also index the parts: "ldl-c" -> "ldl", "c"
            tokens.extend(stem(p) for p in re.split(r"[-/]", tok) if p and p not in STOPWORDS and len(p) > 1)
    return tokens


def content_terms(text: str) -> set[str]:
    """Meaningful terms for overlap checks: no stopwords, no 1–2 letter tokens."""
    return {t for t in tokenize(text) if len(t) > 2}


# ---------------------------------------------------------------------------
# Numbers with units (used to stop invented values or doses)
# ---------------------------------------------------------------------------

_NAMED_DIGITS = re.compile(r"(?i:\b(vitamin\s+[a-z])[-\s]?(\d{1,2})\b)|\b([A-Z])-(\d{1,2})\b|(?i:\b(omega)-(\d)\b)")
_NUMBER = re.compile(
    r"(?<![\w.])(\d+(?:[.,]\d+)?)(?:\s*(%|percent|mg/dl|mmol/l|g/dl|mg|mcg|µg|ug|g|kg|ml|l|iu|units?|mmhg|"
    r"tablets?|capsules?|times|hours?|days?|weeks?|months?|years?))?(?![\w])",
    re.IGNORECASE,
)


def extract_numbers(text: str) -> set[str]:
    """Numeric values (normalised) appearing in text, e.g. {'5.7', '126', '200'}."""
    nums = set()
    # Digits that are part of a name are not values: "vitamin B-12" == "vitamin B12", "omega-3", "T-4".
    text = _NAMED_DIGITS.sub(lambda m: "".join(g for g in m.groups() if g), normalize_unicode(text))
    for m in _NUMBER.finditer(text):
        value = m.group(1).replace(",", ".")
        if re.fullmatch(r"\d+\.0+", value):
            value = value.split(".")[0]
        nums.add(value)
    return nums


def normalize_for_match(text: str) -> str:
    """Lowercase, unify quotes/dashes, collapse whitespace, drop trailing punctuation."""
    text = normalize_unicode(text).lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .;:,")
