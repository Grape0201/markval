from app.services.block_builder import PageBlocks, BlockInfo, WordInfo, DocumentBlocks
from app.services.bbox_resolver import (
    _clean_and_parse_value,
    _refine_bbox_in_block,
    _refine_bbox_by_text,
    _merge_boxes,
    _normalize_block_id,
    resolve_item_bbox,
    resolve_all_bboxes,
)


def test_clean_and_parse_value():
    assert _clean_and_parse_value("1,200.5") == 1200.5
    assert _clean_and_parse_value(" -3.14 ") == -3.14
    assert _clean_and_parse_value("abc") is None
    assert _clean_and_parse_value("12.34.56") is None


def test_normalize_block_id():
    assert _normalize_block_id("B001/paragraph") == "B001"
    assert _normalize_block_id("T001-R2/table_row") == "T001-R2"
    assert _normalize_block_id(" B002 ") == "B002"


def test_merge_boxes():
    boxes = [[10, 20, 50, 40], [20, 10, 60, 30]]
    assert _merge_boxes(boxes) == [10, 10, 60, 40]


def test_refine_bbox_in_block():
    block_box = [10, 10, 100, 50]
    page_words = [
        {"content": "1,200", "box": [20, 20, 60, 35]},
        {"content": "other", "box": [15, 15, 30, 25]},
        {"content": "1,200", "box": [150, 150, 200, 170]}, # outside block
    ]

    # Matching numeric value inside block
    assert _refine_bbox_in_block(block_box, 1200.0, page_words) == [20, 20, 60, 35]
    # No match
    assert _refine_bbox_in_block(block_box, 999.0, page_words) is None


def test_refine_bbox_by_text():
    block_box = [10, 10, 100, 50]
    page_words = [
        {"content": "SUS304-Grade", "box": [20, 20, 60, 35]},
        {"content": "concrete", "box": [70, 20, 95, 35]},
    ]

    # Exact match (none here)
    assert _refine_bbox_by_text(block_box, "concrete", page_words) == [70, 20, 95, 35]
    # Partial match
    assert _refine_bbox_by_text(block_box, "SUS304", page_words) == [20, 20, 60, 35]
    # No match
    assert _refine_bbox_by_text(block_box, "Wood", page_words) is None


def test_resolve_item_bbox():
    block_map = {
        "B001": BlockInfo(block_id="B001", block_type="paragraph", text="Value is 1500", box=[10, 10, 100, 50])
    }
    words = [
        WordInfo(content="1500", box=[50, 15, 80, 30], rec_score=0.99)
    ]
    page_blocks = PageBlocks(page=1, formatted_text="", block_map=block_map, words=words)

    # 1. Numeric value resolution
    item_numeric = {
        "value_type": "numeric",
        "numeric_value": 1500.0,
        "source_block_ids": ["B001/paragraph"]
    }
    resolved = resolve_item_bbox(item_numeric, page_blocks)
    assert resolved["block_id_valid"] is True
    assert resolved["bbox_coarse"] == [10, 10, 100, 50]
    assert resolved["bbox_refined"] == [50, 15, 80, 30]
    assert resolved["bbox"] == [50, 15, 80, 30]

    # 2. Text value resolution
    item_text = {
        "value_type": "name",
        "text_value": "1500",
        "source_block_ids": ["B001"]
    }
    resolved_text = resolve_item_bbox(item_text, page_blocks)
    assert resolved_text["bbox"] == [50, 15, 80, 30]


def test_resolve_all_bboxes():
    block_map_1 = {
        "B001": BlockInfo(block_id="B001", block_type="paragraph", text="100.0", box=[10, 10, 50, 30])
    }
    page_blocks_1 = PageBlocks(page=1, formatted_text="", block_map=block_map_1, words=[])
    
    doc_blocks = DocumentBlocks(source="doc.pdf", pages=[page_blocks_1])

    items = [
        {
            "page": 1,
            "value_type": "numeric",
            "numeric_value": 100.0,
            "source_block_ids": ["B001"]
        },
        {
            "page": 2,  # Page 2 does not exist in doc_blocks
            "value_type": "numeric",
            "numeric_value": 200.0,
            "source_block_ids": ["B002"]
        }
    ]

    results = resolve_all_bboxes(items, doc_blocks)
    assert len(results) == 2
    
    # Page 1 item should have dict formatted bboxes
    assert results[0]["bbox"] == {"x0": 10, "y0": 10, "x1": 50, "y1": 30}
    assert results[0]["bbox_coarse"] == {"x0": 10, "y0": 10, "x1": 50, "y1": 30}
    assert results[0]["bbox_refined"] is None  # no word refinement mock

    # Page 2 item should have None bboxes and invalid block id indicators
    assert results[1]["bbox"] is None
    assert results[1]["block_id_valid"] is False
