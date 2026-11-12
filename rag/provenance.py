"""Locate retrieved text in original PDF pages without changing the vector index."""

import bisect
import re

import pymupdf


def normalize(text: str) -> str:
    return " ".join(text.split())


class PaperSource:
    def __init__(self, path):
        self.source = path.stem + ".txt"
        self.page_starts = []
        parts = []
        offset = 0
        body_end = None
        if path.exists():
            with pymupdf.open(path) as document:
                for index, page in enumerate(document):
                    raw = page.get_text()
                    text = normalize(raw) + " "
                    self.page_starts.append(offset)
                    if body_end is None and index >= len(document) // 2:
                        match = re.search(
                            r"(?im)^\s*(?:\d+[. ]+)?(?:references|bibliography)\s*$",
                            raw,
                        )
                        if match:
                            body_end = offset + len(normalize(raw[: match.start()]))
                    parts.append(text)
                    offset += len(text)
        self.text = "".join(parts)
        self.body_end = body_end if body_end is not None else len(self.text)

    def passage(self, text, limit=1200):
        text = normalize(text)
        start = self.text.find(text) if self.text else -1
        if self.text and start < 0:
            return None  # An unlocatable indexed chunk must not acquire a PDF citation.
        if start >= self.body_end and self.text:
            return None
        if start >= 0:
            text = text[: min(limit, self.body_end - start)].strip()
        else:
            # Legacy text-only sources cannot supply verified page numbers.
            if re.search(r"(?i)\b(?:references|bibliography)\b", text[:100]):
                return None
            text = text[:limit]
        if not text:
            return None
        return {
            "source": self.source,
            "text": text,
            "page_start": bisect.bisect_right(self.page_starts, start)
            if start >= 0
            else None,
            "page_end": bisect.bisect_right(self.page_starts, start + len(text) - 1)
            if start >= 0
            else None,
        }
