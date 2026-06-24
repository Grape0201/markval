"""ブロック ID → Bbox 解決 + Phase 2 精密検索.

PoC-3 の step3_resolve_bbox.py を再利用可能なサービスとして移植。
"""

from __future__ import annotations

import re
from typing import Any

from app.services.block_builder import DocumentBlocks, PageBlocks


# ---------------------------------------------------------------------------
# 数値パース
# ---------------------------------------------------------------------------


def _clean_and_parse_value(text: str) -> float | None:
    """カンマ区切り等を考慮して数値をパースする."""
    candidate = text.strip()
    if not re.match(r"^-?[0-9,]+(\.[0-9]+)?$", candidate):
        return None
    cleaned = candidate.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Phase 2: ブロック内精密検索
# ---------------------------------------------------------------------------


def _refine_bbox_in_block(
    block_box: list[int],
    target_value: float,
    page_words: list[dict[str, Any]],
) -> list[int] | None:
    """ブロック Bbox 内の単語から target_value に一致するものを探す.

    見つかった場合はその単語の Bbox を返し、見つからない場合は None を返す。
    """
    bx0, by0, bx1, by1 = block_box

    # ブロック領域内の単語を絞り込む（余裕を持たせて ±5px）
    margin = 5
    candidates: list[dict[str, Any]] = []
    for w in page_words:
        wx0, wy0, wx1, wy1 = w["box"]
        if (
            wx0 >= bx0 - margin
            and wx1 <= bx1 + margin
            and wy0 >= by0 - margin
            and wy1 <= by1 + margin
        ):
            candidates.append(w)

    # 数値マッチング
    for w in candidates:
        val = _clean_and_parse_value(w["content"])
        if val is not None and abs(val - target_value) < 1e-5:
            return w["box"]

    return None


_NAME_REFINE_MAX_LEN = 20  # これ以下の長さの name 値のみ精密検索を試みる


def _refine_bbox_by_text(
    block_box: list[int],
    target_text: str,
    page_words: list[dict[str, Any]],
) -> list[int] | None:
    """ブロック Bbox 内の単語から target_text に一致するものを探す.

    完全一致 → 部分一致（target_text が単語に含まれる）の優先順で検索する。
    """
    bx0, by0, bx1, by1 = block_box
    margin = 5

    candidates: list[dict[str, Any]] = []
    for w in page_words:
        wx0, wy0, wx1, wy1 = w["box"]
        if (
            wx0 >= bx0 - margin
            and wx1 <= bx1 + margin
            and wy0 >= by0 - margin
            and wy1 <= by1 + margin
        ):
            candidates.append(w)

    # 完全一致
    for w in candidates:
        if w["content"] == target_text:
            return w["box"]

    # 部分一致（target_text が単語の一部として含まれる場合）
    for w in candidates:
        if target_text in w["content"]:
            return w["box"]

    return None


# ---------------------------------------------------------------------------
# Bbox 解決
# ---------------------------------------------------------------------------


def _merge_boxes(boxes: list[list[int]]) -> list[int]:
    """複数の Bbox をマージする (min x0, min y0, max x1, max y1)."""
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    return [x0, y0, x1, y1]


def _normalize_block_id(raw_id: str) -> str:
    """LLM が返すブロック ID を正規化する.

    LLM が ``B002/paragraph`` のようにタイプ注釈を含めて返す場合があるため、
    ``/paragraph`` や ``/table_row`` 等のサフィックスを除去する。
    """
    # "B002/paragraph" → "B002", "T001-R2/table_row" → "T001-R2"
    if "/" in raw_id:
        return raw_id.split("/")[0].strip()
    return raw_id.strip()


def resolve_item_bbox(
    item: dict[str, Any],
    page_blocks: PageBlocks,
) -> dict[str, Any]:
    """1 アイテムのブロック ID を Bbox に解決する.

    Returns:
        アイテムに以下のフィールドを追加して返す:
        - bbox_coarse: ブロック Bbox（Phase 1）
        - bbox_refined: 精密 Bbox（Phase 2、数値のみ）
        - bbox: 最終的に採用する Bbox
        - block_id_valid: 全ての source_block_ids が有効か
        - invalid_block_ids: 無効だった ID のリスト
    """
    source_ids: list[str] = item.get("source_block_ids", [])
    block_map = page_blocks.block_map

    # ブロック ID の正規化 + 有効性チェック
    valid_ids: list[str] = []
    invalid_ids: list[str] = []
    for raw_bid in source_ids:
        bid = _normalize_block_id(raw_bid)
        if bid in block_map:
            valid_ids.append(bid)
        else:
            invalid_ids.append(raw_bid)

    item["block_id_valid"] = len(invalid_ids) == 0
    item["invalid_block_ids"] = invalid_ids

    if not valid_ids:
        item["bbox_coarse"] = None
        item["bbox_refined"] = None
        item["bbox"] = None
        return item

    # Phase 1: ブロック Bbox のマージ
    block_boxes = [block_map[bid].box for bid in valid_ids]
    coarse_box = _merge_boxes(block_boxes)
    item["bbox_coarse"] = coarse_box

    # Phase 2: ブロック内精密検索
    refined_box = None
    value_type = item.get("value_type", "numeric")
    words_dicts = [w.model_dump() for w in page_blocks.words]

    if value_type == "numeric":
        numeric_value = item.get("numeric_value")
        if numeric_value is not None:
            refined_box = _refine_bbox_in_block(
                coarse_box, numeric_value, words_dicts
            )
    elif value_type == "name":
        text_value = item.get("text_value") or ""
        if 0 < len(text_value) <= _NAME_REFINE_MAX_LEN:
            refined_box = _refine_bbox_by_text(
                coarse_box, text_value, words_dicts
            )

    item["bbox_refined"] = refined_box
    # 精密 Bbox があればそちらを採用、なければ粗い Bbox をフォールバック
    item["bbox"] = refined_box if refined_box else coarse_box
    return item


def _bbox_list_to_dict(bbox: list[int]) -> dict[str, int]:
    """list[int] 形式の bbox を annotator 互換の dict 形式に変換する."""
    return {"x0": bbox[0], "y0": bbox[1], "x1": bbox[2], "y1": bbox[3]}


def resolve_all_bboxes(
    items: list[dict[str, Any]],
    doc_blocks: DocumentBlocks,
) -> list[dict[str, Any]]:
    """全アイテムの Bbox を一括解決する.

    アイテムを page ごとにグループ化し、対応する PageBlocks を参照して
    Bbox を解決する。最終的な bbox は annotator サービスとの互換性のため
    ``{"x0": .., "y0": .., "x1": .., "y1": ..}`` の dict 形式に変換する。

    Args:
        items: 抽出済みアイテムのリスト。各アイテムには ``page`` キーが必要。
        doc_blocks: ドキュメント全体のブロック構造。

    Returns:
        Bbox 解決済みアイテムのリスト。
    """
    # ページ番号 → PageBlocks の辞書を構築
    blocks_by_page: dict[int, PageBlocks] = {
        pb.page: pb for pb in doc_blocks.pages
    }

    resolved: list[dict[str, Any]] = []
    for item in items:
        page_num = item.get("page")
        page_blocks = blocks_by_page.get(page_num) if page_num is not None else None

        if page_blocks is None:
            item["bbox_coarse"] = None
            item["bbox_refined"] = None
            item["bbox"] = None
            item["block_id_valid"] = False
            item["invalid_block_ids"] = item.get("source_block_ids", [])
        else:
            resolve_item_bbox(item, page_blocks)

        # bbox を dict 形式に変換
        for key in ("bbox", "bbox_coarse", "bbox_refined"):
            if isinstance(item.get(key), list):
                item[key] = _bbox_list_to_dict(item[key])

        resolved.append(item)

    return resolved
