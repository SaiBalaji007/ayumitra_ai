"""Turn trusted HTML pages and PDFs into heading-delimited sections of clean text."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from ..text import clean_text

# Ingestion only accepts these hosts. Add a domain only after checking its licence/terms.
TRUSTED_HOSTS = {
    "medlineplus.gov",
    "www.medlineplus.gov",
    "www.who.int",
    "who.int",
    "dailymed.nlm.nih.gov",
    "www.ncbi.nlm.nih.gov",
    "pubmed.ncbi.nlm.nih.gov",
    "www.nhs.uk",
}

DEFAULT_SKIP_HEADINGS = {
    "references", "related health topics", "related medical tests", "related topics", "learn more",
    "see, play and learn", "clinical trials", "journal articles", "find an expert", "reference desk",
    "statistics and research", "test your knowledge", "resources", "for you", "research", "genetics",
    "start here", "patient handouts", "multimedia", "images",
}


@dataclass
class RawSection:
    heading_path: list[str]
    text: str
    page: int | None = None


@dataclass
class LoadedDocument:
    title: str
    sections: list[RawSection]
    published_date: str | None = None
    meta: dict = field(default_factory=dict)


class UntrustedSourceError(ValueError):
    pass


def assert_trusted(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in TRUSTED_HOSTS:
        raise UntrustedSourceError(f"{url} is not on the trusted-source allowlist (https only).")


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_DATE_PATTERNS = [
    re.compile(r"(?:Last updated|Page last updated|Updated)\s*:?\s*([A-Z][a-z]+ \d{1,2}, \d{4})"),
    re.compile(r"(?:Last updated|Updated)\s*:?\s*(\d{1,2} [A-Z][a-z]+ \d{4})"),
    re.compile(r"reviewed (\d{4} [A-Z][a-z]{2} \d{1,2})"),
]


def find_published_date(text: str) -> str | None:
    for pat in _DATE_PATTERNS:
        if m := pat.search(text):
            return m.group(1)
    return None


def load_html(html: str, *, content_selector: str | None = None, skip_headings: list[str] | None = None) -> LoadedDocument:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    full_text = soup.get_text(" ", strip=True)
    published = find_published_date(full_text)

    title_el = soup.find("h1") or soup.find("title")
    title = clean_text(title_el.get_text(" ", strip=True)) if title_el else "Untitled"

    root = soup.select_one(content_selector) if content_selector else None
    root = root or soup.find("main") or soup.find("article") or soup.body or soup
    for tag in root.select("script, style, nav, footer, header, form, noscript, svg, button, iframe, aside"):
        tag.decompose()

    skip = DEFAULT_SKIP_HEADINGS | {h.lower() for h in (skip_headings or [])}
    sections: list[RawSection] = []
    path: list[tuple[int, str]] = [(1, title)]
    buffer: list[str] = []
    skipping = False

    def flush():
        text = clean_text("\n".join(buffer))
        if text and not skipping:
            sections.append(RawSection(heading_path=[h for _, h in path], text=text))
        buffer.clear()

    for el in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "dd", "dt"]):
        if el.name in ("h1", "h2", "h3", "h4"):
            flush()
            level = int(el.name[1])
            heading = clean_text(el.get_text(" ", strip=True))
            if not heading:
                continue
            if level == 1:
                path = [(1, heading)]
                skipping = False
                continue
            path = [p for p in path if p[0] < level] + [(level, heading)]
            # A skipped heading skips everything until a heading at the same or higher level.
            skipping = any(h.lower().strip(" :?") in skip for _, h in path[1:])
            continue
        # Avoid double counting: <li><p>text</p></li> -> only the innermost block element.
        if el.find(["p", "li"]):
            continue
        text = el.get_text(" ", strip=True)
        if text:
            buffer.append(("- " if el.name == "li" else "") + text)
    flush()
    return LoadedDocument(title=title, sections=sections, published_date=published)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _repeated_lines(pages: list[list[str]], min_ratio: float = 0.6) -> set[str]:
    """Lines that appear on most pages (running headers/footers, page numbers)."""
    if len(pages) < 3:
        return set()
    counts = Counter()
    for lines in pages:
        counts.update({re.sub(r"\d+", "#", ln.strip().lower()) for ln in lines if ln.strip()})
    return {ln for ln, c in counts.items() if c / len(pages) >= min_ratio}


def load_pdf(path: Path) -> LoadedDocument:
    """Extract text per page with PyMuPDF; detect headings from font size; drop running headers."""
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    # (text, size, bold, in_margin). Only lines in the top/bottom margin can be running headers or
    # footers; numbered headings in the body ("Chapter 2 ...") must never be dropped as repeats.
    page_lines: list[list[tuple[str, float, bool, bool]]] = []
    sizes = Counter()
    for page in doc:
        lines = []
        height = page.rect.height or 1
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                text = "".join(s["text"] for s in spans).strip()
                if not text:
                    continue
                size = max(s["size"] for s in spans)
                bold = any("bold" in s.get("font", "").lower() for s in spans)
                y0, y1 = line["bbox"][1], line["bbox"][3]
                in_margin = y1 <= height * 0.08 or y0 >= height * 0.92
                lines.append((text, size, bold, in_margin))
                if not in_margin:
                    sizes[round(size)] += len(text)
        page_lines.append(lines)

    body_size = sizes.most_common(1)[0][0] if sizes else 10
    repeated = _repeated_lines([[t for t, _, _, m in lines if m] for lines in page_lines])
    meta_title = (doc.metadata or {}).get("title") or path.stem.replace("_", " ").title()

    sections: list[RawSection] = []
    heading = meta_title
    buffer: list[str] = []
    current_page = 1

    def flush(page_no: int):
        text = clean_text("\n".join(buffer))
        if text:
            sections.append(RawSection(heading_path=[meta_title, heading] if heading != meta_title else [meta_title], text=text, page=page_no))
        buffer.clear()

    for page_no, lines in enumerate(page_lines, start=1):
        for text, size, bold, in_margin in lines:
            if in_margin and re.sub(r"\d+", "#", text.lower()) in repeated:
                continue
            is_heading = (size >= body_size + 1.5 or (bold and size >= body_size)) and len(text.split()) <= 14 and not text.endswith(".")
            if is_heading:
                flush(current_page)
                heading, current_page = text, page_no
            else:
                if not buffer:
                    current_page = page_no
                buffer.append(text)
        # keep sections page-attributed: flush at page end
        flush(current_page)
        current_page = page_no + 1

    full = "\n".join(t for lines in page_lines for t, *_ in lines)
    return LoadedDocument(title=meta_title, sections=sections, published_date=find_published_date(full), meta={"pages": len(doc)})


# ---------------------------------------------------------------------------
# DailyMed Structured Product Labels (FDA drug labels, public domain)
# ---------------------------------------------------------------------------

# LOINC section codes kept for patient education. Dosage & Administration (34068-7) and
# overdosage/clinical pharmacology are deliberately EXCLUDED: AyuMitra must not give dose advice.
SPL_SECTIONS = {
    "42231-1": "Medication Guide",
    "42230-3": "Patient Package Insert",
    "34076-0": "Patient Counseling Information",
    "34067-9": "Indications and Usage",
    "34070-3": "Contraindications",
    "43685-7": "Warnings and Precautions",
    "34071-1": "Warnings",
    "42232-9": "Precautions",
    "34084-4": "Adverse Reactions",
    "34073-7": "Drug Interactions",
    "44425-7": "Storage and Handling",
    "50741-8": "Safe Handling Warning",
}


def load_spl(xml: str) -> LoadedDocument:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(xml, "html.parser")  # tag names are lowercased; fine for SPL
    title_el = soup.find("title")
    title = clean_text(title_el.get_text(" ", strip=True)) if title_el else "Drug label"
    eff = soup.find("effectivetime")
    published = eff.get("value") if eff is not None else None
    if published and len(published) >= 8:
        published = f"{published[:4]}-{published[4:6]}-{published[6:8]}"

    sections: list[RawSection] = []
    for sec in soup.find_all("section"):
        code_el = sec.find("code", recursive=False)
        code = code_el.get("code") if code_el is not None else None
        if code not in SPL_SECTIONS:
            continue
        # Skip if an ancestor section is already a kept section (avoid duplicating nested text).
        if any(((p.find("code", recursive=False) or {}).get("code") in SPL_SECTIONS) for p in sec.find_parents("section")):
            continue
        heading = SPL_SECTIONS[code]
        sec_title = sec.find("title", recursive=False)
        blocks = []
        for el in sec.find_all(["paragraph", "item", "td", "title"]):
            if el is sec_title or el.find(["paragraph", "item"]):
                continue
            t = el.get_text(" ", strip=True)
            if t:
                blocks.append(("- " if el.name == "item" else "") + t)
        text = clean_text("\n".join(blocks))
        if text:
            sections.append(RawSection(heading_path=[title, heading], text=text))
    return LoadedDocument(title=title, sections=sections, published_date=published)
