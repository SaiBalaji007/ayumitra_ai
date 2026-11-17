"""
Section-aware, semantic chunking.

1. Never cross a section boundary: every chunk belongs to exactly one heading path, and its
   section is kept as the chunk's *parent* for wider context (parent-child retrieval).
2. Inside a section, pack whole sentences up to a word budget, with a one-sentence overlap.
3. With an embedder, also start a new chunk where the topic shifts, i.e. where the cosine
   similarity between neighbouring sentences drops below a threshold (semantic chunking).
"""

from __future__ import annotations

import hashlib

import numpy as np

from ..models import Embedder
from ..schemas import Chunk, Domain, Section
from ..text import split_sentences, word_count
from .loaders import LoadedDocument


def _id(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()[:12]


def build_sections(source_id: str, doc: LoadedDocument, parent_max_words: int = 600) -> list[Section]:
    sections = []
    for order, raw in enumerate(doc.sections):
        words = raw.text.split()
        text = raw.text if len(words) <= parent_max_words else " ".join(words[:parent_max_words]) + " ..."
        sections.append(
            Section(
                id=f"{source_id}#s{order}-{_id(source_id, str(order), raw.text[:200])}",
                source_id=source_id, heading_path=raw.heading_path, text=text, page=raw.page, order=order,
            )
        )
    return sections


def _semantic_breaks(sentences: list[str], embedder: Embedder | None, threshold: float) -> set[int]:
    """Indices i where a new chunk should start before sentence i."""
    if embedder is None or len(sentences) < 3:
        return set()
    vecs = embedder.embed_passages(sentences)
    sims = np.sum(vecs[:-1] * vecs[1:], axis=1)
    return {i + 1 for i, s in enumerate(sims) if s < threshold}


def chunk_section(
    section: Section,
    *,
    domain: Domain,
    title: str,
    target_words: int = 140,
    max_words: int = 220,
    overlap_sentences: int = 1,
    embedder: Embedder | None = None,
    semantic_threshold: float = 0.25,
    min_words_before_semantic_split: int = 40,
) -> list[Chunk]:
    sents = split_sentences(section.text)
    if not sents:
        return []
    texts = [s for s, _, _ in sents]
    breaks = _semantic_breaks(texts, embedder, semantic_threshold)

    def is_item(j: int) -> bool:
        return texts[j].lstrip().startswith(("-", "•", "*"))

    groups: list[list[int]] = []
    current: list[int] = []
    words = 0
    lead_in: int | None = None  # the "... may be a sign of:" sentence introducing the current list
    for i, sent in enumerate(texts):
        w = word_count(sent)
        topic_shift = i in breaks and words >= min_words_before_semantic_split
        over_budget = current and words + w > max_words
        reached_target = current and words >= target_words
        # A list must stay with its lead-in: never split right after "...:" or between two items of
        # one list unless the hard budget forces it. Otherwise neither chunk can support a claim like
        # "low hemoglobin may be a sign of blood loss" (lead-in in one chunk, items in the next).
        prev = current[-1] if current else None
        inside_list = prev is not None and is_item(i) and (texts[prev].rstrip().endswith(":") or is_item(prev))
        if inside_list and not over_budget:
            topic_shift = reached_target = False
        if current and (topic_shift or over_budget or reached_target):
            groups.append(current)
            keep = current[-overlap_sentences:] if overlap_sentences and not topic_shift else []
            if inside_list and lead_in is not None and lead_in not in keep:
                keep = [lead_in, *[k for k in keep if k != lead_in]]  # repeat the lead-in for context
            current, words = list(keep), sum(word_count(texts[j]) for j in keep)
        if sent.rstrip().endswith(":"):
            lead_in = i
        elif not is_item(i):
            lead_in = None
        current.append(i)
        words += w
    if current:  # always holds at least one sentence not yet emitted
        groups.append(current)

    context = " > ".join([title, *section.heading_path[1:]])
    chunks = []
    for order, idx in enumerate(groups):
        start, end = sents[idx[0]][1], sents[idx[-1]][2]
        text = section.text[start:end]  # exact slice of the source text
        chunks.append(
            Chunk(
                id=f"{section.id}c{order}",
                source_id=section.source_id,
                section_id=section.id,
                domain=domain,
                text=text,
                embed_text=f"{context}: {text}",
                heading_path=section.heading_path,
                page=section.page,
                order=order,
                word_count=word_count(text),
            )
        )
    return chunks
