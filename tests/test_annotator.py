from pathlib import Path
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from app.services.annotator import annotate_pdf_file_a, annotate_pdf_file_b


def create_dummy_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path))
    c.drawString(100, 750, "Sample calculation sheet page 1")
    c.showPage()
    c.drawString(100, 750, "Sample calculation sheet page 2")
    c.showPage()
    c.save()


def test_annotate_pdf_file_a(tmp_path):
    # Arrange
    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    create_dummy_pdf(input_pdf)

    # Prepare dummy checklist items (File A)
    items_a = [
        {
            "id": "item-1",
            "label": "屋根 固定荷重",
            "value": 1200.0,
            "unit": "N/m²",
            "page": 1,
            "bbox": {"x0": 50, "y0": 100, "x1": 150, "y1": 120},
            "context": "屋根の固定荷重は1200N/m²とする。"
        },
        {
            "id": "item-2",
            "label": "床 積載荷重",
            "value": 2900.0,
            "unit": "N/m²",
            "page": 2,
            "bbox": {"x0": 60, "y0": 150, "x1": 160, "y1": 170},
            "context": "床の積載荷重は2900N/m²とする。"
        }
    ]

    # Prepare dummy match results
    results = [
        {
            "check_item_id": "item-1",
            "matched": True,
            "confidence": 0.95,
            "ai_reasoning": "数値と単位が一致しています。",
            "matched_source_label": "屋根の標準固定荷重",
            "matched_source_value": 1200.0,
            "matched_source_unit": "N/m²",
            "matched_source_page": 3
        },
        {
            "check_item_id": "item-2",
            "matched": False,
            "confidence": 0.5,
            "ai_reasoning": "一致するデータが見つかりませんでした。",
            "matched_source_label": "",
            "matched_source_value": 0.0,
            "matched_source_unit": "",
            "matched_source_page": 0
        }
    ]

    # Act
    annotate_pdf_file_a(input_pdf, items_a, results, output_pdf)

    # Assert
    assert output_pdf.exists()
    assert output_pdf.stat().st_size > 0

    # Read the output PDF to verify it's valid and has the correct number of pages
    reader = PdfReader(output_pdf)
    assert len(reader.pages) == 2


def test_annotate_pdf_file_b(tmp_path):
    # Arrange
    input_pdf = tmp_path / "input_b.pdf"
    output_pdf = tmp_path / "output_b.pdf"
    create_dummy_pdf(input_pdf)

    # Prepare dummy source items (File B)
    source_items = [
        {
            "id": "source-item-1",
            "label": "規格 固定荷重",
            "value": 1200.0,
            "unit": "N/m²",
            "page": 1,
            "bbox": {"x0": 50, "y0": 100, "x1": 150, "y1": 120},
            "context_text": "本規格における固定荷重の基準値は1200N/m²です。"
        },
        {
            "id": "source-item-2",
            "label": "規格 積載荷重",
            "value": 3000.0,
            "unit": "N/m²",
            "page": 2,
            "bbox": {"x0": 60, "y0": 150, "x1": 160, "y1": 170},
            "context_text": "本規格における積載荷重の基準値は3000N/m²です。"
        }
    ]

    # Prepare dummy match results referencing source items
    results = [
        {
            "source_item_id": "source-item-1",
            "mapping_id": "c01",
            "check_item_label": "設計 固定荷重",
            "check_item_value": 1200.0,
            "check_item_unit": "N/m²",
            "check_item_page": 3,
            "ai_reasoning": "基準値と一致しています。"
        }
    ]

    # Act
    annotate_pdf_file_b(input_pdf, source_items, results, output_pdf)

    # Assert
    assert output_pdf.exists()
    assert output_pdf.stat().st_size > 0

    # Verify PDF structure
    reader = PdfReader(output_pdf)
    assert len(reader.pages) == 2

