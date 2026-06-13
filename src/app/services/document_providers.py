import io
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx
import pdfplumber
from markitdown import MarkItDown
from pypdf import PdfReader, PdfWriter

from app.core.semaphores import get_yomitoku_semaphore


def _clean_and_parse_value(text: str) -> float | None:
    candidate = text.strip()

    if not re.match(r"^-?[0-9,]+(\.[0-9]+)?$", candidate):
        return None
    cleaned = candidate.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


class DocumentProvider(ABC):
    @abstractmethod
    async def extract_markdown_pages(self, pdf_path: Path) -> list[dict[str, Any]]:
        """Extract markdown content for each page of the PDF."""
        raise NotImplementedError

    @abstractmethod
    def annotate(
        self, pdf_path: Path, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Locate items on the PDF page and add bounding box (bbox) information."""
        raise NotImplementedError


class LocalProvider(DocumentProvider):
    async def extract_markdown_pages(self, pdf_path: Path) -> list[dict[str, Any]]:
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        reader = PdfReader(pdf_path)
        markitdown_converter = MarkItDown()
        pages_data = []

        for idx in range(len(reader.pages)):
            page_num = idx + 1

            # Write single page to a BytesIO stream
            writer = PdfWriter()
            writer.add_page(reader.pages[idx])

            pdf_stream = io.BytesIO()
            writer.write(pdf_stream)
            pdf_stream.seek(0)

            # Convert page to markdown
            result = markitdown_converter.convert_stream(
                pdf_stream, mime_type="application/pdf"
            )
            markdown_text = result.text_content

            pages_data.append({"page": page_num, "markdown": markdown_text})

        return pages_data

    def annotate(
        self, pdf_path: Path, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        updated_items = []

        with pdfplumber.open(pdf_path) as pdf:
            for item in items:
                label = item["label"]
                target_value = item["value"]
                page_num = item["page"]
                context = item.get("context") or item.get("context_text") or ""

                if page_num < 1 or page_num > len(pdf.pages):
                    item["bbox"] = None
                    updated_items.append(item)
                    continue

                page = pdf.pages[page_num - 1]
                words = page.extract_words()

                # Group words to lines for context comparison
                words_sorted = sorted(words, key=lambda w: (w["top"], w["x0"]))
                lines = []
                if words_sorted:
                    current_group = [words_sorted[0]]
                    for w in words_sorted[1:]:
                        avg_top = sum(item["top"] for item in current_group) / len(
                            current_group
                        )
                        if abs(w["top"] - avg_top) < 3.0:
                            current_group.append(w)
                        else:
                            lines.append(current_group)
                            current_group = [w]
                    lines.append(current_group)

                line_texts = []
                line_mappings = []
                for line in lines:
                    line_words_sorted = sorted(line, key=lambda w: w["x0"])
                    text = " ".join(w["text"] for w in line_words_sorted)
                    line_texts.append(text)
                    line_mappings.append(line_words_sorted)

                # Find candidate words representing target_value
                candidates = []
                for line_idx, line_words in enumerate(line_mappings):
                    for word in line_words:
                        word_val = _clean_and_parse_value(word["text"])
                        if word_val is not None and abs(word_val - target_value) < 1e-5:
                            candidates.append((word, line_texts[line_idx]))

                if not candidates:
                    item["bbox"] = None
                    updated_items.append(item)
                    continue

                # Disambiguate candidates using token intersection
                best_word = None
                best_score = -1.0
                keywords = set(re.findall(r"\w+", label) + re.findall(r"\w+", context))

                for word, line_text in candidates:
                    line_tokens = set(re.findall(r"\w+", line_text))
                    matches = len(keywords.intersection(line_tokens))
                    score = float(matches)
                    if score > best_score:
                        best_score = score
                        best_word = word

                if best_word:
                    bbox = {
                        "x0": round(float(best_word["x0"]), 1),
                        "y0": round(float(best_word["top"]), 1),
                        "x1": round(float(best_word["x1"]), 1),
                        "y1": round(float(best_word["bottom"]), 1),
                    }
                    item["bbox"] = bbox
                else:
                    item["bbox"] = None

                updated_items.append(item)

        return updated_items


async def _call_yomitoku_api(pdf_path: Path) -> dict[str, Any]:
    """
    TODO: Implement actual Yomitoku OCR API call.
    Currently uses dummy httpx call and returns mock OCR layout & markdown data.
    """
    semaphore = get_yomitoku_semaphore()
    async with semaphore:
        async with httpx.AsyncClient():
            # Dummy async call to simulate Yomitoku API call
            # e.g., async with httpx.AsyncClient() as client:
            #           res = await client.get("https://httpbin.org/delay/1")
            # In a real implementation, we would post the PDF to Yomitoku OCR API:
            # files = {"file": open(pdf_path, "rb")}
            # res = await client.post("https://api.yomitoku.example/ocr", files=files)
            pass

        # Return a mocked response matching the expected Yomitoku OCR response structure.
        # Note: Yomitoku can return both markdown and layout box data.
        try:
            reader = PdfReader(pdf_path)
            num_pages = len(reader.pages)
        except Exception:
            num_pages = 1

        mock_pages = []
        for i in range(num_pages):
            page_num = i + 1
            mock_pages.append(
                {
                    "page": page_num,
                    "markdown": f"# Yomitoku OCR Page {page_num}\nThis is dummy text representing the extracted markdown from page {page_num}.\nExample target value: 100.0\n",
                    "data": {
                        "paragraphs": [
                            {
                                "contents": f"Example target value: 100.0 on page {page_num}",
                                "box": [50.0, 100.0, 200.0, 120.0],  # [x0, y0, x1, y1]
                            }
                        ],
                        "text_blocks": [],
                        "tables": [],
                    },
                }
            )

        return {"pages": mock_pages}


class YomitokuProvider(DocumentProvider):
    def __init__(self) -> None:
        self._cached_pages: list[dict[str, Any]] = []

    async def extract_markdown_pages(self, pdf_path: Path) -> list[dict[str, Any]]:
        # Call the dummy OCR API
        api_response = await _call_yomitoku_api(pdf_path)
        self._cached_pages = api_response.get("pages", [])

        # Format return value as list of {"page": int, "markdown": str}
        pages_data = []
        for page in self._cached_pages:
            pages_data.append(
                {"page": page["page"], "markdown": page.get("markdown", "")}
            )
        return pages_data

    def annotate(
        self, pdf_path: Path, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        # Map page layouts from cached Yomitoku response
        entries_by_page = {
            page.get("page"): self._build_page_entries(page)
            for page in self._cached_pages
        }

        updated_items: list[dict[str, Any]] = []
        for item in items:
            page_num = item["page"]
            label = item["label"]
            context = item.get("context") or item.get("context_text") or ""
            target_value = item["value"]

            page_entries = entries_by_page.get(page_num) or []
            best_entry = self._select_entry(page_entries, label, context, target_value)

            if best_entry:
                item["bbox"] = {
                    "x0": round(best_entry["box"][0], 1),
                    "y0": round(best_entry["box"][1], 1),
                    "x1": round(best_entry["box"][2], 1),
                    "y1": round(best_entry["box"][3], 1),
                }
            else:
                item["bbox"] = None

            updated_items.append(item)

        return updated_items

    def _build_page_entries(self, page_payload: dict[str, Any]) -> list[dict[str, Any]]:
        data = page_payload.get("data") or {}
        entries: list[dict[str, Any]] = []

        for paragraph in data.get("paragraphs", []):
            self._add_entry(entries, paragraph.get("contents"), paragraph.get("box"))

        for block in data.get("text_blocks", []):
            self._add_entry(entries, block.get("content"), block.get("box"))

        for table in data.get("tables", []):
            for cell in table.get("cells", []):
                self._add_entry(entries, cell.get("contents"), cell.get("box"))

        return entries

    @staticmethod
    def _add_entry(
        entries: list[dict[str, Any]], text: str | None, box: list[float] | None
    ) -> None:
        if not text or not box:
            return
        entries.append({"text": text, "box": box})

    def _select_entry(
        self,
        entries: list[dict[str, Any]],
        label: str,
        context: str,
        target_value: float,
    ) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []
        for entry in entries:
            text = entry["text"]
            for match in re.finditer(r"-?[0-9,]+(?:\.[0-9]+)?", text):
                candidate_value = _clean_and_parse_value(match.group())
                if candidate_value is None:
                    continue
                if abs(candidate_value - target_value) < 1e-5:
                    candidates.append(entry)
                    break

        if not candidates:
            return None

        keywords = set(re.findall(r"\w+", label) + re.findall(r"\w+", context))

        def score(entry: dict[str, Any]) -> float:
            tokens = set(re.findall(r"\w+", entry["text"]))
            return float(len(tokens.intersection(keywords)))

        return max(candidates, key=score)
