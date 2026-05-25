from __future__ import annotations
import re
from dataclasses import dataclass

from ..config import settings


@dataclass(frozen=True)
class TextChunk:
    text: str
    ordinal: int
    char_start: int
    char_end: int


# Sentence boundary: period/question/exclamation followed by whitespace + capital,
# or a markdown heading, or a blank line.
_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_PARA_RE = re.compile(r"\n\s*\n+")


def _split_paragraphs(text: str) -> list[tuple[str, int]]:
    """Return (paragraph_text, char_offset) pairs."""
    result: list[tuple[str, int]] = []
    last = 0
    for m in _PARA_RE.finditer(text):
        fragment = text[last : m.start()].strip()
        if fragment:
            result.append((fragment, last))
        last = m.end()
    tail = text[last:].strip()
    if tail:
        result.append((tail, last))
    return result or [(text, 0)]


def chunk_text(
    text: str,
    size: int | None = None,
    overlap: int | None = None,
) -> list[TextChunk]:
    """
    Split *text* into overlapping chunks of approximately *size* characters.

    Strategy:
      1. Split on paragraph boundaries first.
      2. If a paragraph fits in the current buffer, accumulate it.
      3. When the buffer would overflow, flush as a chunk and seed the next
         buffer with the last *overlap* characters of the flushed text
         (so that cross-boundary context is preserved).
      4. Paragraphs larger than *size* are split at sentence boundaries.
    """
    size = size or settings.chunk_size
    overlap = overlap if overlap is not None else settings.chunk_overlap

    paragraphs = _split_paragraphs(text)
    chunks: list[TextChunk] = []
    buf = ""
    buf_start = 0
    ordinal = 0

    def flush(b: str, start: int) -> None:
        nonlocal ordinal
        stripped = b.strip()
        if stripped:
            chunks.append(
                TextChunk(
                    text=stripped,
                    ordinal=ordinal,
                    char_start=start,
                    char_end=start + len(b),
                )
            )
            ordinal += 1

    def _overlap_seed(b: str, start: int) -> tuple[str, int]:
        """Return (seed_text, seed_start) for the overlap window."""
        if overlap <= 0 or len(b) <= overlap:
            return "", start + len(b)
        seed = b[-overlap:]
        return seed.strip(), start + len(b) - overlap

    for para, para_start in paragraphs:
        # Paragraph too big on its own → split at sentence boundaries
        if len(para) > size:
            sentences = _SENT_RE.split(para)
            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue
                if len(buf) + len(sent) + 2 > size and buf:
                    flush(buf, buf_start)
                    buf, buf_start = _overlap_seed(buf, buf_start)
                buf = (buf + "  " + sent).strip() if buf else sent
            continue

        if len(buf) + len(para) + 2 > size and buf:
            flush(buf, buf_start)
            buf, buf_start = _overlap_seed(buf, buf_start)

        if not buf:
            buf_start = para_start
        buf = (buf + "\n\n" + para).strip() if buf else para

    flush(buf, buf_start)
    return chunks
