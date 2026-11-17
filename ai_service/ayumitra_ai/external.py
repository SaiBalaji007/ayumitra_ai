"""
External trusted sources, used only when the local knowledge base can't answer a question.

  - MedlinePlus health topics, via the official NLM search web service (wsearch.nlm.nih.gov).
    Public domain text by the U.S. National Library of Medicine. Returns the topic summary and its
    official alternate names (e.g. "Vitamin E", also called "Alpha-tocopherol").
  - MeSH definitions (U.S. National Library of Medicine), via NCBI E-utilities: medical terms,
    procedures and chemicals without a MedlinePlus page.
  - FDA drug labels, via openFDA (api.fda.gov). Only patient-education sections are used
    (indications, adverse reactions, warnings, patient information). Dosage sections are never used.

Fetched text goes through the same pipeline as local passages: reranker relevance gate, evidence
compression, LLM claims, citation validation. Each passage keeps its real public URL. Responses are
cached on disk for a week so repeated questions don't hit the services again.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

USER_AGENT = "AyuMitraAI/1.0 (health education; local)"
CACHE_TTL_S = 7 * 24 * 3600
MEDLINEPLUS_SEARCH = "https://wsearch.nlm.nih.gov/ws/query"
OPENFDA_LABEL = "https://api.fda.gov/drug/label.json"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
FDA_SECTIONS = (  # patient-education sections only; never dosage_and_administration
    ("indications_and_usage", "Uses"),
    ("adverse_reactions", "Side effects"),
    ("warnings_and_cautions", "Warnings and precautions"),
    ("warnings", "Warnings"),
)

_QUESTION_WORDS = re.compile(
    r"\b(what|whats|what's|is|are|was|were|does|do|did|can|could|should|would|will|why|how|when|which|who|"
    r"the|a|an|of|for|in|on|to|my|me|i|it|its|this|that|and|or|with|mean|means|meaning|tell|about|please|"
    r"explain|common|people|someone|have|has|test|measure|measures|level|levels|normal|range|eat)\b",
    re.I,
)


@dataclass
class ExternalDoc:
    id: str
    title: str
    url: str
    publisher: str
    text: str
    published_date: str | None = None


def _strip_html(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    for li in soup.find_all("li"):
        li.insert_before("\n- ")
    for p in soup.find_all(["p", "ul", "ol", "br"]):
        p.insert_after("\n")
    text = soup.get_text()
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


_GENERIC_WORDS = re.compile(
    r"\b(benefits?|causes?|symptoms?|signs?|side|effects?|risks?|difference|between|purpose|uses?|used|"
    r"treatment|foods?|diet|good|bad|high|low)\b", re.I)


def core_terms(question: str) -> str:
    """The topic words only: 'benefits Vitamin D' -> 'Vitamin D'."""
    words = [w for w in search_terms(question).split() if not _GENERIC_WORDS.fullmatch(w)]
    return " ".join(words)


def search_terms(question: str) -> str:
    """'What are the common side effects of Metformin?' -> 'side effects Metformin'."""
    q = re.sub(r"[^\w\s\-]", " ", question)
    words = [w for w in q.split() if not _QUESTION_WORDS.fullmatch(w)]
    return " ".join(words) or question.strip()


def candidate_terms(question: str, max_terms: int = 5) -> list[str]:
    """Search strings from most to least specific. The NLM search ANDs its words, so a long question
    ("Salivary gland stones; surgical creation of an opening ...") must also be tried in parts."""
    terms = [core_terms(question), search_terms(question)]
    parts = [p for p in re.split(r"[;,/]|\band\b", question) if p.strip()]
    if len(parts) > 1:
        terms += [core_terms(p) for p in parts]
    words = core_terms(question).split()
    if len(words) > 3:
        terms += [" ".join(words[:3]), " ".join(words[:2])]
    return [t for t in dict.fromkeys(t.strip() for t in terms) if t][:max_terms]


class ExternalSources:
    def __init__(self, cache_dir: Path, *, timeout_s: float = 20.0, enabled: bool = True, wikipedia_contact: str = ""):
        self.cache_dir = Path(cache_dir)
        self.timeout_s = timeout_s
        self.enabled = enabled
        self.wikipedia_contact = wikipedia_contact.strip()

    # ------------------------------------------------------------------ http + cache
    def _get(self, url: str, params: dict, *, user_agent: str = USER_AGENT) -> str | None:
        import httpx

        key = hashlib.sha256((url + json.dumps(params, sort_keys=True)).encode()).hexdigest()[:24]
        path = self.cache_dir / f"{key}.txt"
        if path.exists() and time.time() - path.stat().st_mtime < CACHE_TTL_S:
            return path.read_text(encoding="utf-8")
        try:
            resp = httpx.get(url, params=params, headers={"User-Agent": user_agent}, timeout=self.timeout_s,
                             follow_redirects=True)
        except httpx.HTTPError as exc:
            log.warning("External source unreachable (%s): %s", url, exc)
            return None
        if resp.status_code == 404:  # openFDA: no match
            body = ""
        elif resp.status_code != 200:
            log.warning("External source %s returned HTTP %s", url, resp.status_code)
            return None
        else:
            body = resp.text
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return body

    # ------------------------------------------------------------------ MedlinePlus
    def medlineplus(self, question: str, *, limit: int = 3) -> list[ExternalDoc]:
        docs, seen = [], set()
        for term in candidate_terms(question):
            for d in self._medlineplus_term(term, limit):
                if d.url not in seen:
                    seen.add(d.url)
                    docs.append(d)
        return docs

    def _medlineplus_term(self, term: str, limit: int) -> list[ExternalDoc]:
        body = self._get(MEDLINEPLUS_SEARCH, {"db": "healthTopics", "term": term, "retmax": limit})
        if not body:
            return []
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return []
        docs = []
        for d in root.iter("document"):
            fields: dict[str, list[str]] = {}
            for c in d.findall("content"):
                fields.setdefault(c.get("name", ""), []).append(_strip_html("".join(c.itertext())))
            url = d.get("url", "")
            title = (fields.get("title") or [""])[0]
            summary = (fields.get("FullSummary") or [""])[0]
            if not (url.startswith("https://medlineplus.gov/") and title and summary):
                continue
            alt = [a for a in fields.get("altTitle", []) if a and a.lower() != title.lower()]
            head = f"{title}." + (f" Also called: {', '.join(alt)}." if alt else "")
            docs.append(ExternalDoc(id=f"ext-mlp-{hashlib.sha1(url.encode()).hexdigest()[:10]}", title=title, url=url,
                                    publisher=(fields.get("organizationName") or ["National Library of Medicine"])[0],
                                    text=f"{head}\n{summary}"))
        return docs

    # ------------------------------------------------------------------ openFDA
    def fda_label(self, medicine: str) -> ExternalDoc | None:
        name = re.sub(r"[^a-z0-9 \-]", "", medicine.lower()).strip()
        if not name:
            return None
        body = self._get(OPENFDA_LABEL, {"search": f'openfda.generic_name:"{name}"', "limit": 10})
        if not body:
            return None
        try:
            results = json.loads(body).get("results", [])
        except json.JSONDecodeError:
            return None

        def single_ingredient(r):
            names = r.get("openfda", {}).get("generic_name", [])
            return len(names) == 1 and " and " not in names[0].lower() and "," not in names[0]

        label = next((r for r in results if single_ingredient(r)), None)
        if label is None:
            return None
        parts = []
        for key, heading in FDA_SECTIONS:
            vals = label.get(key) or []
            if vals:
                text = re.sub(r"^\s*\d+(\.\d+)?\s+[A-Z &]+\b", "", vals[0]).strip()  # drop "6 ADVERSE REACTIONS"
                text = re.sub(r"\(\s*\d+(\.\d+)*\s*\)", "", text)                    # drop "( 5.1 )" refs
                parts.append(f"{heading}:\n{text[:1800]}")
        if not parts:
            return None
        generic = label["openfda"]["generic_name"][0].title()
        set_id = label.get("set_id", "")
        return ExternalDoc(id=f"ext-fda-{set_id[:12]}", title=f"{generic}: FDA drug label",
                           url=f"https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={set_id}",
                           publisher="U.S. Food and Drug Administration (via openFDA / DailyMed)",
                           text="\n".join(parts), published_date=label.get("effective_time"))

    # ------------------------------------------------------------------ MeSH (NLM)
    def mesh(self, question: str, *, limit: int = 3) -> list[ExternalDoc]:
        """Definitions ("scope notes") from MeSH, the U.S. National Library of Medicine's medical
        vocabulary, via NCBI E-utilities. Covers diseases, procedures, chemicals, anatomy and tests that
        have no MedlinePlus page (e.g. dacryocystorhinostomy, salivary gland calculi). Public domain."""
        uids: list[str] = []
        for term in candidate_terms(question):
            body = self._get(EUTILS + "esearch.fcgi", {"db": "mesh", "term": term, "retmode": "json", "retmax": limit})
            try:
                uids += json.loads(body or "{}").get("esearchresult", {}).get("idlist", [])
            except json.JSONDecodeError:
                pass
            if len(dict.fromkeys(uids)) >= limit:
                break
        uids = list(dict.fromkeys(uids))[:limit]
        if not uids:
            return []
        body = self._get(EUTILS + "esummary.fcgi", {"db": "mesh", "id": ",".join(uids), "retmode": "json"})
        try:
            result = json.loads(body or "{}").get("result", {})
        except json.JSONDecodeError:
            return []
        docs = []
        for uid in uids:
            d = result.get(uid) or {}
            names = [n for n in d.get("ds_meshterms", []) if n]
            note = (d.get("ds_scopenote") or "").strip()
            if not names or len(note) < 20:
                continue
            title = names[0]
            alt = [n for n in names[1:6] if "," not in n]  # skip inverted forms like "Calculi, Salivary Gland"
            text = f"{title}." + (f" Also called: {', '.join(alt)}." if alt else "") + f"\n{note}"
            docs.append(ExternalDoc(id=f"ext-mesh-{uid}", title=f"{title} (MeSH)",
                                    url=f"https://www.ncbi.nlm.nih.gov/mesh/{uid}",
                                    publisher="MeSH, U.S. National Library of Medicine", text=text))
        return docs

    # ------------------------------------------------------------------ Wikipedia
    def wikipedia(self, question: str, *, limit: int = 2) -> list[ExternalDoc]:
        """Intro sections of the best-matching English Wikipedia articles (CC BY-SA). Broad coverage of
        medical terms and procedures. Only called for questions confirmed to be about health, after the
        official sources; text still passes the relevance gate and citation validation."""
        if not (self.enabled and self.wikipedia_contact):
            return []
        ua = f"AyuMitraAI/1.0 ({self.wikipedia_contact}; health-education app)"
        titles: list[str] = []
        for term in candidate_terms(question, max_terms=3):
            body = self._get(WIKIPEDIA_API, {"action": "query", "list": "search", "srsearch": term,
                                             "srlimit": limit, "format": "json"}, user_agent=ua)
            try:
                hits = json.loads(body or "{}").get("query", {}).get("search", [])
            except json.JSONDecodeError:
                hits = []
            titles += [h["title"] for h in hits if h.get("title")]
            if len(dict.fromkeys(titles)) >= limit:
                break
        docs = []
        for title in list(dict.fromkeys(titles))[:limit]:
            body = self._get(WIKIPEDIA_API, {"action": "query", "prop": "extracts|info", "inprop": "url",
                                             "exintro": 1, "explaintext": 1, "redirects": 1, "titles": title,
                                             "format": "json"}, user_agent=ua)
            try:
                pages = json.loads(body or "{}").get("query", {}).get("pages", {})
            except json.JSONDecodeError:
                continue
            for page in pages.values():
                text = (page.get("extract") or "").strip()
                if len(text) < 80 or "may refer to" in text[:300]:
                    continue  # missing or disambiguation page
                url = page.get("fullurl") or f"https://en.wikipedia.org/wiki/{page.get('title', title).replace(' ', '_')}"
                docs.append(ExternalDoc(id=f"ext-wiki-{page.get('pageid')}", title=f"{page.get('title', title)} (Wikipedia)",
                                        url=url, publisher="Wikipedia (community encyclopedia, CC BY-SA)",
                                        text=text[:4000]))
        return docs

    # ------------------------------------------------------------------ medicine information (Phase 3)
    def medicine_info(self, medicine: str) -> dict | None:
        """FDA label sections for one medicine (single-ingredient label), trimmed for display. Dosage and
        administration are never included. None if no label matches the exact generic name."""
        import datetime as _dt

        name = re.sub(r"[^a-z0-9 \-]", "", medicine.lower()).strip()
        if not name:
            return None
        body = self._get(OPENFDA_LABEL, {"search": f'openfda.generic_name:"{name}"', "limit": 10})
        try:
            results = json.loads(body or "{}").get("results", [])
        except json.JSONDecodeError:
            return None
        singles = [r for r in results if len(r.get("openfda", {}).get("generic_name", [])) == 1
                   and " and " not in r["openfda"]["generic_name"][0].lower()]
        # Prescriptions are mostly tablets/capsules: prefer an oral label over injections or topicals.
        singles.sort(key=lambda r: "ORAL" not in [x.upper() for x in r.get("openfda", {}).get("route", [])])
        label = singles[0] if singles else None
        if label is None:
            return None

        def section(*keys, limit=350):
            for k in keys:
                vals = label.get(k) or []
                if vals:
                    t = re.sub(r"^\s*\d+(\.\d+)?\s+[A-Z &]+\b", "", vals[0]).strip()
                    t = re.sub(r"\(\s*\d+(\.\d+)*\s*\)|\[\s*see [^\]]*\]", "", t)
                    t = re.sub(r"\s+", " ", t).strip()
                    if len(t) > limit:  # cut at a sentence end
                        cut = t[:limit].rfind(". ")
                        t = t[: cut + 1 if cut > 200 else limit].rstrip() + " …"
                    return t
            return ""

        of = label.get("openfda", {})
        set_id = label.get("set_id", "")
        return {
            "query": medicine,
            "generic_name": of.get("generic_name", [""])[0].title(),
            "brand_names": sorted(set(of.get("brand_name", [])))[:5],
            "drug_class": "; ".join(of.get("pharm_class_epc", [])[:2]),
            "uses": section("indications_and_usage"),
            "side_effects": section("adverse_reactions"),
            "warnings": section("boxed_warning", "warnings_and_cautions", "warnings"),
            "contraindications": section("contraindications"),
            "interactions_note": section("drug_interactions", limit=300),
            "source_title": f"{of.get('generic_name', [''])[0].title()}: FDA drug label (DailyMed)",
            "source_url": f"https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={set_id}",
            "label_effective": label.get("effective_time"),
            "retrieved": _dt.date.today().isoformat(),
        }

    # ------------------------------------------------------------------ combined
    def search(self, question: str, *, medicines: list[str] = ()) -> list[ExternalDoc]:
        if not self.enabled:
            return []
        docs = []
        for m in list(dict.fromkeys(medicines))[:2]:
            d = self.fda_label(m)
            if d:
                docs.append(d)
        docs.extend(self.medlineplus(question))
        docs.extend(self.mesh(question))
        return docs


def as_dict(doc: ExternalDoc) -> dict:
    return asdict(doc)
