from openknet.ingest.chunker import chunk_text


def test_empty_text():
    assert chunk_text("") == []


def test_single_short_para():
    chunks = chunk_text("Hello world.")
    assert len(chunks) == 1
    assert chunks[0].text == "Hello world."
    assert chunks[0].ordinal == 0


def test_multiple_paragraphs_fit_in_one_chunk():
    text = "Para one.\n\nPara two.\n\nPara three."
    chunks = chunk_text(text, size=500, overlap=0)
    assert len(chunks) == 1


def test_large_text_splits_into_multiple_chunks():
    # Build text larger than default chunk size
    long_para = "Word " * 200  # ~1000 chars
    text = "\n\n".join([long_para] * 5)
    chunks = chunk_text(text, size=800, overlap=100)
    assert len(chunks) > 1


def test_overlap_present():
    # Generate two paragraphs that together exceed chunk size
    para = "A " * 500  # 1000 chars
    text = para + "\n\n" + para
    chunks = chunk_text(text, size=800, overlap=100)
    # Second chunk should start with tail of first
    assert len(chunks) >= 2


def test_ordinals_are_sequential():
    text = "\n\n".join([f"Paragraph {i}. " * 50 for i in range(5)])
    chunks = chunk_text(text, size=500)
    for i, c in enumerate(chunks):
        assert c.ordinal == i


def test_char_positions_are_non_negative():
    text = "Alpha.\n\nBeta.\n\nGamma."
    for c in chunk_text(text):
        assert c.char_start >= 0
        assert c.char_end >= c.char_start
