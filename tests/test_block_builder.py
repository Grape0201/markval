from app.services.yomitoku_models import Page, Paragraph, Table, TableCell, TableRow, TableCol, Word
from app.services.block_builder import (
    _points_to_box,
    _build_table_rows,
    build_page_blocks,
    build_document_blocks,
)


def test_points_to_box():
    # Polygon points to bounding box
    points = [[10, 20], [30, 20], [30, 40], [10, 40]]
    box = _points_to_box(points)
    assert box == [10, 20, 30, 40]


def test_build_table_rows():
    # Construct a mock Table
    table = Table(
        box=[10, 10, 100, 100],
        n_row=2,
        n_col=2,
        rows=[
            TableRow(box=[10, 10, 100, 50], score=0.9),
            TableRow(box=[10, 50, 100, 100], score=0.9),
        ],
        cols=[
            TableCol(box=[10, 10, 50, 100], score=0.9),
            TableCol(box=[50, 10, 100, 100], score=0.9),
        ],
        spans=[],
        cells=[
            TableCell(col=0, row=0, col_span=1, row_span=1, box=[10, 10, 50, 50], contents="A1"),
            TableCell(col=1, row=0, col_span=1, row_span=1, box=[50, 10, 100, 50], contents="B1"),
            TableCell(col=0, row=1, col_span=1, row_span=1, box=[10, 50, 50, 100], contents="A2"),
            TableCell(col=1, row=1, col_span=1, row_span=1, box=[50, 50, 100, 100], contents="B2"),
        ],
        order=2,
    )

    rows = _build_table_rows(table, table_idx=1)
    # Check that we got 2 rows
    assert len(rows) == 2
    
    # First row formatting
    formatted_1, info_1, header_1 = rows[0]
    assert formatted_1 == "[T001-R0] | A1 | B1 |"
    assert info_1.block_id == "T001-R0"
    assert info_1.block_type == "table_row"
    assert info_1.text == "A1 | B1"
    assert info_1.box == [10, 10, 100, 50]
    assert header_1 == "【テーブル T001】"

    # Second row formatting
    formatted_2, info_2, header_2 = rows[1]
    assert formatted_2 == "[T001-R1] | A2 | B2 |"
    assert info_2.block_id == "T001-R1"
    assert header_2 is None


def test_build_page_blocks():
    # Construct a page with paragraph and table, and words
    page = Page(
        paragraphs=[
            Paragraph(box=[10, 10, 200, 30], contents="Hello World", direction="horizontal", order=1)
        ],
        tables=[
            Table(
                box=[10, 40, 200, 90],
                n_row=1,
                n_col=1,
                rows=[TableRow(box=[10, 40, 200, 90], score=0.9)],
                cols=[TableCol(box=[10, 40, 200, 90], score=0.9)],
                spans=[],
                cells=[TableCell(col=0, row=0, col_span=1, row_span=1, box=[10, 40, 200, 90], contents="TableData")],
                order=3,
            )
        ],
        words=[
            Word(points=[[10, 10], [50, 10], [50, 25], [10, 25]], content="Hello", direction="horizontal", rec_score=0.99, det_score=0.99),
            Word(points=[[60, 10], [100, 10], [100, 25], [60, 25]], content="World", direction="horizontal", rec_score=0.99, det_score=0.99),
        ],
    )

    page_blocks = build_page_blocks(page, page_num=5)

    assert page_blocks.page == 5
    # The formatted text should contain paragraph B001 and table row T001-R0
    assert "[B001/paragraph] Hello World" in page_blocks.formatted_text
    assert "[T001-R0] | TableData |" in page_blocks.formatted_text

    # Check block map keys
    assert "B001" in page_blocks.block_map
    assert "T001-R0" in page_blocks.block_map

    # Check block_map block content
    assert page_blocks.block_map["B001"].text == "Hello World"
    assert page_blocks.block_map["B001"].box == [10, 10, 200, 30]

    # Check words
    assert len(page_blocks.words) == 2
    assert page_blocks.words[0].content == "Hello"
    assert page_blocks.words[0].box == [10, 10, 50, 25]


def test_build_document_blocks():
    # Construct doc blocks from pages list
    page_1 = Page(paragraphs=[Paragraph(box=[10, 10, 100, 20], contents="P1", direction="horizontal", order=1)])
    page_2 = Page(paragraphs=[Paragraph(box=[20, 20, 120, 30], contents="P2", direction="horizontal", order=1)])

    doc_blocks = build_document_blocks([page_1, page_2], source="test_doc.pdf")

    assert doc_blocks.source == "test_doc.pdf"
    assert len(doc_blocks.pages) == 2
    assert doc_blocks.pages[0].page == 1
    assert "[B001/paragraph] P1" in doc_blocks.pages[0].formatted_text
    assert doc_blocks.pages[1].page == 2
    assert "[B001/paragraph] P2" in doc_blocks.pages[1].formatted_text
