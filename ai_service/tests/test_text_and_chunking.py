from ayumitra_ai.ingestion.chunking import build_sections, chunk_section
from ayumitra_ai.ingestion.loaders import LoadedDocument, RawSection
from ayumitra_ai.models import HashingEmbedder
from ayumitra_ai.schemas import Domain
from ayumitra_ai.text import clean_text, extract_numbers, split_sentences, stem, tokenize


class TestSentences:
    def test_offsets_slice_back_to_the_same_text(self):
        text = "First sentence here. Second one has 5.7 percent!  Third?"
        for sent, start, end in split_sentences(text):
            assert text[start:end] == sent

    def test_decimals_and_abbreviations_do_not_split(self):
        text = "An A1C of 6.5 percent or higher, e.g. on two tests, suggests something. Next sentence."
        sents = [s for s, _, _ in split_sentences(text)]
        assert sents == ["An A1C of 6.5 percent or higher, e.g. on two tests, suggests something.", "Next sentence."]

    def test_line_breaks_end_list_items(self):
        sents = [s for s, _, _ in split_sentences("- item one\n- item two\nA sentence.")]
        assert sents == ["- item one", "- item two", "A sentence."]


class TestTokenize:
    def test_keeps_medical_tokens_and_their_parts(self):
        toks = tokenize("HbA1c and LDL-C in mg/dL")
        assert "hba1c" in toks
        assert "ldl-c" in toks and "ldl" in toks
        assert "mg/dl" in toks

    def test_removes_stopwords_and_stems_lightly(self):
        assert tokenize("The tests are measuring levels") == ["test", "measur", "level"]
        assert stem("diabetes") == "diabete"  # consistent for query and document; that's what matters
        assert stem("glucose") == "glucose"

    def test_numbers(self):
        assert extract_numbers("between 70 and 100 mg/dL, or 5.7%, 6,5 units, 120.0") == {"70", "100", "5.7", "6.5", "120"}


def test_clean_text_dehyphenates_and_collapses_space():
    assert clean_text("hemo-\nglobin   levels are\n\n\n\nfine") == "hemoglobin levels are\n\nfine"


def _section(text, heading=("Doc", "Results")):
    doc = LoadedDocument(title="Doc", sections=[RawSection(heading_path=list(heading), text=text)])
    return build_sections("src", doc)[0]


class TestChunking:
    def test_chunks_are_exact_slices_and_stay_in_section(self):
        text = " ".join(f"Sentence number {i} talks about zentrine levels." for i in range(40))
        sec = _section(text)
        chunks = chunk_section(sec, domain=Domain.LAB_TESTS, title="Doc", target_words=40, max_words=60)
        assert len(chunks) > 3
        for ch in chunks:
            assert ch.text in sec.text
            assert ch.section_id == sec.id and ch.heading_path == ["Doc", "Results"]
            assert ch.word_count <= 60
            assert ch.embed_text.startswith("Doc > Results: ")

    def test_overlap_of_one_sentence(self):
        text = " ".join(f"Fact {i} is stated in this sentence here." for i in range(20))
        chunks = chunk_section(_section(text), domain=Domain.GENERAL, title="Doc", target_words=30, max_words=50,
                               overlap_sentences=1)
        for a, b in zip(chunks, chunks[1:]):
            last_of_a = split_sentences(a.text)[-1][0]
            assert b.text.startswith(last_of_a)

    def test_covers_every_sentence(self):
        text = " ".join(f"Point {i} matters a lot." for i in range(25))
        chunks = chunk_section(_section(text), domain=Domain.GENERAL, title="Doc", target_words=20, max_words=30)
        joined = " ".join(c.text for c in chunks)
        for i in range(25):
            assert f"Point {i} matters" in joined

    def test_semantic_split_at_topic_shift(self):
        a = " ".join("Zentrine protein levels rise in Kelvara blood samples." for _ in range(8))
        b = " ".join("Quorvin plinth minerals appear in urine stones." for _ in range(8))
        chunks = chunk_section(_section(a + " " + b), domain=Domain.GENERAL, title="Doc", target_words=500,
                               max_words=600, embedder=HashingEmbedder(), semantic_threshold=0.5,
                               min_words_before_semantic_split=20)
        assert len(chunks) == 2
        assert "Quorvin" not in chunks[0].text and "Zentrine" not in chunks[1].text

    def test_short_section_is_single_chunk(self):
        chunks = chunk_section(_section("Only one sentence."), domain=Domain.GENERAL, title="Doc")
        assert [c.text for c in chunks] == ["Only one sentence."]


def test_digits_inside_names_are_not_values():
    """Regression: 'vitamin B-12' made the citation check reject a correct, well-cited claim."""
    from ayumitra_ai.text import extract_numbers

    assert extract_numbers("Lack of nutrients such as iron or vitamin B-12") == set()
    assert extract_numbers("omega-3 fats, T-4 and vitamin D 3") == set()
    assert extract_numbers("B-12 of 150 pg/mL") == {"150"}
    assert extract_numbers("a 1-2 day stay, type 2 diabetes, fast 9 to 12 hours") == {"1", "2", "9", "12"}


def test_list_stays_with_its_lead_in():
    """Regression: 'Low hemoglobin levels may be a sign of:' ended one chunk and its bullets began the
    next, so no single chunk supported a correct answer."""
    from ayumitra_ai.ingestion.chunking import chunk_section
    from ayumitra_ai.schemas import Domain, Section

    intro = " ".join(f"Sentence {i} explains how zentrine results are reported by the lab." for i in range(12))
    text = (intro + " Low zentrine levels may be a sign of:\n- Blood loss from injury\n- Lack of certain nutrients\n"
            "High zentrine levels may be a sign of:\n- Kelvara syndrome")
    sec = Section(id="s1", source_id="src", heading_path=["Zentrox", "Results"], text=text, page=None, order=0)
    chunks = chunk_section(sec, domain=Domain.LAB_TESTS, title="Zentrox", target_words=60, max_words=200)
    holder = [c.text for c in chunks if "Blood loss" in c.text]
    assert holder and all("Low zentrine levels may be a sign of:" in t for t in holder)
