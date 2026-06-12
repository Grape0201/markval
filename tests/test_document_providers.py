import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from reportlab.pdfgen import canvas

from app.services.document_providers import LocalProvider, YomitokuProvider

def create_dummy_pdf(path: Path, text: str, value_str: str = "1200.0") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path))
    # Write text and a numerical value at specific coordinates
    # reportlab coordinates: origin is bottom-left of the page
    c.drawString(100, 750, f"{text} {value_str}")
    c.showPage()
    c.save()


@pytest.mark.anyio
async def test_local_provider_extract_and_annotate(tmp_path):
    pdf_path = tmp_path / "dummy_local.pdf"
    create_dummy_pdf(pdf_path, "Test Document Page 1", "1200.0")

    provider = LocalProvider()

    # 1. Test extraction
    # Mock MarkItDown conversion to avoid dependency oddities or external calls
    mock_convert_result = MagicMock()
    mock_convert_result.text_content = "Test Document Page 1 1200.0"
    
    with patch("app.services.document_providers.MarkItDown") as mock_markitdown:
        mock_instance = MagicMock()
        mock_instance.convert_stream.return_value = mock_convert_result
        mock_markitdown.return_value = mock_instance

        pages = await provider.extract_markdown_pages(pdf_path)
        assert len(pages) == 1
        assert pages[0]["page"] == 1
        assert "1200.0" in pages[0]["markdown"]

    # 2. Test annotation
    # Items to annotate
    items = [
        {
            "label": "Test Item",
            "value": 1200.0,
            "page": 1,
            "context": "Test Document Page 1 1200.0"
        }
    ]

    annotated = provider.annotate(pdf_path, items)
    assert len(annotated) == 1
    bbox = annotated[0]["bbox"]
    assert bbox is not None
    assert "x0" in bbox
    assert "y0" in bbox
    assert "x1" in bbox
    assert "y1" in bbox


@pytest.mark.anyio
async def test_yomitoku_provider_extract_and_annotate(tmp_path):
    pdf_path = tmp_path / "dummy_yomitoku.pdf"
    create_dummy_pdf(pdf_path, "Yomitoku Text", "100.0")

    provider = YomitokuProvider()

    # 1. Test extraction (will call _call_yomitoku_api under the hood)
    pages = await provider.extract_markdown_pages(pdf_path)
    assert len(pages) == 1
    assert pages[0]["page"] == 1
    assert "Yomitoku OCR Page 1" in pages[0]["markdown"]

    # 2. Test annotation using cached layout from the Yomitoku mock response
    items = [
        {
            "label": "Example target value",
            "value": 100.0,
            "page": 1,
            "context_text": "Example target value: 100.0 on page 1"
        }
    ]

    annotated = provider.annotate(pdf_path, items)
    assert len(annotated) == 1
    bbox = annotated[0]["bbox"]
    assert bbox is not None
    # The dummy response has box: [50.0, 100.0, 200.0, 120.0]
    assert bbox["x0"] == 50.0
    assert bbox["y0"] == 100.0
    assert bbox["x1"] == 200.0
    assert bbox["y1"] == 120.0
