import pytest

from ayumitra_ai.ingestion.loaders import UntrustedSourceError, assert_trusted, load_html, load_pdf
from ayumitra_ai.ingestion.pipeline import load_manifest
from ayumitra_ai.schemas import Domain
from ayumitra_ai.store.vector_store import collection_name

from .conftest import ZENTROX_HTML


class TestHtmlLoader:
    def test_sections_follow_headings_and_skip_boilerplate(self):
        doc = load_html(ZENTROX_HTML, content_selector="#content")
        assert doc.title == "Zentrox Test"
        paths = [s.heading_path for s in doc.sections]
        assert ["Zentrox Test", "What is a Zentrox test?"] in paths
        assert all("References" not in p for p in paths)
        text = " ".join(s.text for s in doc.sections)
        assert "Menu" not in text and "must be skipped" not in text
        assert "- It may be part of a routine checkup." in text

    def test_published_date_found(self):
        assert load_html(ZENTROX_HTML).published_date == "March 3, 2025"

    def test_nested_blocks_not_duplicated(self):
        doc = load_html("<div><h1>T</h1><h2>S</h2><ul><li><p>Once only.</p></li></ul></div>")
        assert " ".join(s.text for s in doc.sections).count("Once only.") == 1


class TestTrust:
    @pytest.mark.parametrize("url", ["https://medlineplus.gov/lab-tests/x/", "https://www.who.int/news-room/fact-sheets/x"])
    def test_trusted(self, url):
        assert_trusted(url)

    @pytest.mark.parametrize("url", ["http://medlineplus.gov/x", "https://medlineplus.gov.evil.com/x", "https://randomblog.com/x"])
    def test_untrusted(self, url):
        with pytest.raises(UntrustedSourceError):
            assert_trusted(url)


def test_pdf_loader_detects_headings_pages_and_drops_running_headers(tmp_path):
    import fitz

    pdf = fitz.open()
    for i in range(3):
        page = pdf.new_page()
        page.insert_text((72, 40), "Fictional Health Guide - Confidential Header", fontsize=9)
        page.insert_text((72, 90), f"Chapter {i + 1} Heading", fontsize=18)
        page.insert_text((72, 130), f"Body text on page {i + 1} about zentrine.", fontsize=11)
        page.insert_text((72, 800), f"Page {i + 1}", fontsize=9)
    path = tmp_path / "guide.pdf"
    pdf.save(path)

    doc = load_pdf(path)
    assert doc.meta["pages"] == 3
    headings = [s.heading_path[-1] for s in doc.sections]
    assert "Chapter 2 Heading" in headings
    joined = " ".join(s.text for s in doc.sections)
    assert "Confidential Header" not in joined and "Page 2" not in joined
    assert {s.page for s in doc.sections} == {1, 2, 3}


def test_real_manifest_is_valid_and_trusted():
    from ayumitra_ai.config import get_settings

    specs = load_manifest(get_settings().sources_manifest)
    assert len(specs) >= 20
    for s in specs:
        assert_trusted(s.url)
        assert "/ency/" not in s.url and "/druginfo/" not in s.url  # licensed MedlinePlus content


class TestIngestor:
    def test_ingest_stores_sources_sections_chunks_and_vectors(self, ingested):
        db, vectors, results = ingested
        assert all(r.chunks > 0 and not r.error for r in results)
        assert db.get_source("test-zentrox").published_date == "March 3, 2025"
        assert vectors.count(Domain.LAB_TESTS) == len(db.chunks(Domain.LAB_TESTS))
        assert vectors.count(Domain.GENERAL) == len(db.chunks(Domain.GENERAL))
        # domains are separate collections
        assert {c.source_id for c in db.chunks(Domain.LAB_TESTS)} == {"test-zentrox"}

    def test_reingest_unchanged_is_skipped_and_changed_replaces(self, settings, embedder, ingested):
        from ayumitra_ai.ingestion.pipeline import Ingestor
        from ayumitra_ai.schemas import SourceSpec

        db, vectors, _ = ingested
        ing = Ingestor(settings, embedder, db, vectors)
        spec = SourceSpec(id="test-zentrox", title="Zentrox Test", url="https://medlineplus.gov/test/zentrox/",
                          domain=Domain.LAB_TESTS, publisher="P", license="test", content_selector="#content")
        assert ing.ingest(spec, content=(ZENTROX_HTML.encode(), "html")).skipped
        changed = ZENTROX_HTML.replace("<h2>References</h2>", "<h2>Extra</h2><p>Brand new fictional paragraph.</p><h2>References</h2>")
        r = ing.ingest(spec, content=(changed.encode(), "html"))
        assert not r.skipped
        chunks = db.chunks(Domain.LAB_TESTS)
        assert any("Brand new fictional paragraph" in c.text for c in chunks)
        assert vectors.count(Domain.LAB_TESTS) == len(chunks)  # old vectors removed, no orphans


def test_collection_names_are_versioned_per_domain_and_model():
    name = collection_name(Domain.LAB_TESTS, "sentence-transformers/all-MiniLM-L6-v2")
    assert name == "kb_lab_tests__all-minilm-l6-v2__v1"
    assert collection_name(Domain.LAB_TESTS, "BAAI/bge-small-en-v1.5") != name
