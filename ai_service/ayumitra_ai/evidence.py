"""
Contextual compression and evidence assembly.

Compression keeps only the sentences of each retrieved chunk that matter for the question
(cross-encoder relevance per sentence), plus their immediate neighbours for coherence. Every
sentence keeps its character offsets into the original chunk, so any quote AyuMitra shows is a
verbatim slice of the source.
"""

from __future__ import annotations

import re

from .models import Reranker
from .schemas import Evidence, EvidenceSentence, RetrievedChunk
from .text import split_sentences, word_count


def compress(
    query: str,
    item: RetrievedChunk,
    reranker: Reranker | None,
    *,
    max_sentences: int = 5,
    neighbours: bool = True,
) -> list[EvidenceSentence]:
    text = item.chunk.text
    sents = split_sentences(text)
    if len(sents) <= max_sentences or reranker is None:
        return [EvidenceSentence(text=s, start=a, end=b) for s, a, b in sents]

    # Units: a list's lead-in ("Low hemoglobin may be a sign of:") plus its "- item" lines form one
    # unit that is scored and kept whole. Scored separately, short items like "- Blood loss" lose to
    # the lead-in, and the evidence ends up as "...may be a sign of:" with the answer cut off.
    def is_item(t: str) -> bool:
        return t.lstrip().startswith(("-", "•", "*"))

    units: list[list[int]] = []
    for i, (t, _, _) in enumerate(sents):
        prev = units[-1] if units else None
        if prev and is_item(t) and (sents[prev[0]][0].rstrip().endswith(":") or is_item(sents[prev[-1]][0])):
            prev.append(i)
        else:
            units.append([i])
    max_unit = max_sentences + 8  # a list may exceed the sentence budget a little; never cut mid-list

    scores = reranker.score(query, [" ".join(sents[i][0] for i in u) for u in units])
    order = sorted(range(len(units)), key=lambda k: scores[k], reverse=True)
    keep: set[int] = set()
    for k in order:
        if len(keep) >= max_sentences:
            break
        group = set(units[k][:max_unit])
        first = units[k][0]
        # A sentence starting with "It"/"This" often needs the one before it.
        if neighbours and len(units[k]) == 1 and first > 0:
            group.add(first - 1)
        if keep and len(keep | group) > max_unit:
            group = set(units[k][:max_unit])
            if len(keep | group) > max_unit:
                continue
        keep |= group
    return [EvidenceSentence(text=sents[i][0], start=sents[i][1], end=sents[i][2]) for i in sorted(keep)]


_TABLE_REF = re.compile(r"\b(table|figure|fig\.)\s*\d", re.I)


def _is_fragment(text: str) -> bool:
    """Pieces left by sentence splitting at an ellipsis or around removed tables (FDA labels)."""
    t = text.strip()
    return not t or t.startswith(("...", "\u2026")) or t[0].islower() or bool(_TABLE_REF.search(t))


def assemble_evidence(
    query: str,
    items: list[RetrievedChunk],
    reranker: Reranker | None,
    *,
    max_sentences: int = 5,
    max_words: int = 900,
) -> list[Evidence]:
    """Numbered evidence blocks E1..En within a word budget, best-ranked first."""
    evidence: list[Evidence] = []
    used = 0
    seen_text: set[str] = set()
    for item in items:
        sentences = [s for s in compress(query, item, reranker, max_sentences=max_sentences)
                     if not _is_fragment(s.text) or s.text.lstrip().startswith(("-", "•", "*"))]
        # Skip a block only when everything in it was already shown. Removing single duplicate
        # sentences (from chunk overlap) used to cut lists apart: "High hemoglobin may be a sign of:
        # - Lung disease ..." lost its "- Sleep apnea" item because the next chunk had shown it first.
        if all(s.text in seen_text for s in sentences):
            continue
        text = " ".join(s.text for s in sentences)
        words = word_count(text)
        if evidence and used + words > max_words:
            break
        seen_text.update(s.text for s in sentences)
        used += words
        ch, src = item.chunk, item.source
        evidence.append(
            Evidence(
                id=f"E{len(evidence) + 1}", chunk_id=ch.id, source_id=ch.source_id, title=src.title, url=src.url,
                section=" > ".join(ch.heading_path[1:]) or src.title, page=ch.page,
                published_date=src.published_date, text=text, sentences=sentences, rerank_score=item.rerank_score,
                publisher=src.publisher, external=src.id.startswith("ext-"),
            )
        )
    return evidence


def format_evidence_for_prompt(evidence: list[Evidence]) -> str:
    blocks = []
    for ev in evidence:
        blocks.append(f"[{ev.id}] Source: {ev.title} | Section: {ev.section}\n{ev.text}")
    return "\n\n".join(blocks)
