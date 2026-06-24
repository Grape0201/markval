"""ブロック構造構築サービス.

Yomitoku OCR の Page オブジェクトからブロック ID 付きテキストと
ID-Bbox 対応表を構築する。PoC-3 の models.py / step1_build_blocks.py を統合。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.services.yomitoku_models import Page, Paragraph, Table

# ---------------------------------------------------------------------------
# Pydantic モデル
# ---------------------------------------------------------------------------


class BlockInfo(BaseModel):
    """ブロック ID → メタデータ."""

    block_id: str
    block_type: Literal["paragraph", "table_row"]
    text: str
    box: list[int]  # [x0, y0, x1, y1] ピクセル座標
    cells: list[dict] | None = None  # table_row の場合のみ


class WordInfo(BaseModel):
    """単語情報（Phase 2 精密検索用）."""

    content: str
    box: list[int]  # [x0, y0, x1, y1]
    rec_score: float


class PageBlocks(BaseModel):
    """1 ページ分のブロック構造."""

    page: int
    formatted_text: str
    block_map: dict[str, BlockInfo]
    words: list[WordInfo]


class DocumentBlocks(BaseModel):
    """ドキュメント全体のブロック構造."""

    source: str
    pages: list[PageBlocks]


class ExtractedItem(BaseModel):
    """LLM が返す抽出アイテム."""

    label: str = Field(
        description="項目名（日本語。部位・荷重種別・パラメータ名等を組み合わせる。"
        "例: '屋根 固定荷重', 'SN400B 降伏点'）",
    )
    value_type: Literal["numeric", "name", "formula"] = Field(
        description="値の種類（現時点では 'numeric' のみ対応）",
    )
    numeric_value: float | None = Field(
        None,
        description="数値（value_type='numeric' の場合。例: 1200, 0.20）",
    )
    text_value: str | None = Field(
        None,
        description="名称やテキスト値（value_type='name' の場合。例: 'SUS304'）",
    )
    formula_value: str | None = Field(
        None,
        description="数式（value_type='formula' の場合。LaTeX 形式推奨）",
    )
    unit: str | None = Field(
        None,
        description="単位（例: 'N/m²', 'N/mm²'。無単位の場合は None）",
    )
    context: str = Field(
        description="抽出箇所の前後の文脈テキスト",
    )
    source_block_ids: list[str] = Field(
        description="抽出の根拠となったブロック ID リスト（例: ['T001-R2']）。"
        "与えられた ID の中から選択すること。存在しない ID を生成しないこと。",
    )
    category: str = Field(
        description="分類カテゴリ",
    )


class PageExtraction(BaseModel):
    """1 ページ分の抽出結果."""

    items: list[ExtractedItem]


# ---------------------------------------------------------------------------
# ブロック構築関数
# ---------------------------------------------------------------------------


def _points_to_box(points: list[list[int]]) -> list[int]:
    """4 隅ポリゴンを [x0, y0, x1, y1] に変換する."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _build_table_rows(
    table: Table, table_idx: int
) -> list[tuple[str, BlockInfo, str | None]]:
    """テーブルを行単位でブロック化する.

    Returns:
        (formatted_line, block_info, table_header_or_none) のリスト
    """
    # セルを行番号でグルーピング
    rows_dict: dict[int, list] = {}
    for cell in table.cells:
        rows_dict.setdefault(cell.row, []).append(cell)

    table_id = f"T{table_idx:03d}"
    header = f"【テーブル {table_id}】"
    result: list[tuple[str, BlockInfo, str | None]] = []

    for row_num in sorted(rows_dict):
        row_cells = sorted(rows_dict[row_num], key=lambda c: c.col)
        row_id = f"{table_id}-R{row_num}"

        # 行内セルの Bbox をマージ
        x0 = min(c.box[0] for c in row_cells)
        y0 = min(c.box[1] for c in row_cells)
        x1 = max(c.box[2] for c in row_cells)
        y1 = max(c.box[3] for c in row_cells)

        cell_texts = [c.contents for c in row_cells]
        formatted = f"[{row_id}] | {' | '.join(cell_texts)} |"

        block_info = BlockInfo(
            block_id=row_id,
            block_type="table_row",
            text=" | ".join(cell_texts),
            box=[x0, y0, x1, y1],
            cells=[
                {"contents": c.contents, "box": list(c.box)} for c in row_cells
            ],
        )

        # テーブルの最初の行にだけヘッダーを付与
        is_first = row_num == min(rows_dict)
        result.append((formatted, block_info, header if is_first else None))

    return result


def build_page_blocks(page: Page, page_num: int) -> PageBlocks:
    """1 ページ分のブロック構造を構築する."""
    # 段落とテーブルを order でソートしてインターリーブ
    items: list[tuple[int, str, Paragraph | Table]] = []
    for para in page.paragraphs:
        items.append((para.order, "paragraph", para))
    for table in page.tables:
        items.append((table.order, "table", table))
    items.sort(key=lambda x: x[0])

    block_map: dict[str, BlockInfo] = {}
    lines: list[str] = []
    block_counter = 0
    table_counter = 0

    for _, item_type, data in items:
        if item_type == "paragraph":
            block_counter += 1
            bid = f"B{block_counter:03d}"
            assert isinstance(data, Paragraph)

            block_info = BlockInfo(
                block_id=bid,
                block_type="paragraph",
                text=data.contents,
                box=list(data.box),
            )
            block_map[bid] = block_info
            lines.append(f"[{bid}/paragraph] {data.contents}")

        elif item_type == "table":
            table_counter += 1
            assert isinstance(data, Table)
            table_rows = _build_table_rows(data, table_counter)

            for formatted, block_info, table_header in table_rows:
                block_map[block_info.block_id] = block_info
                if table_header:
                    lines.append("")
                    lines.append(table_header)
                lines.append(formatted)

    # Word を簡易フォーマットに変換（Phase 2 精密検索用）
    words: list[WordInfo] = []
    for w in page.words:
        box = _points_to_box(w.points)
        words.append(
            WordInfo(content=w.content, box=box, rec_score=w.rec_score)
        )

    return PageBlocks(
        page=page_num,
        formatted_text="\n".join(lines),
        block_map=block_map,
        words=words,
    )


def build_document_blocks(
    ocr_pages: list[Page], source: str = ""
) -> DocumentBlocks:
    """パース済み Page オブジェクトのリストからドキュメント全体のブロック構造を構築する.

    Args:
        ocr_pages: Yomitoku OCR 結果の Page モデルリスト。
        source: ドキュメントのソース名（ファイル名等）。

    Returns:
        DocumentBlocks: ドキュメント全体のブロック構造。
    """
    pages = [
        build_page_blocks(page, page_num=i + 1)
        for i, page in enumerate(ocr_pages)
    ]
    return DocumentBlocks(source=source, pages=pages)
