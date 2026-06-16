"""PoC-3 共有 Pydantic モデル."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# LLM 構造化出力モデル
# ---------------------------------------------------------------------------


class ExtractedItem(BaseModel):
    """LLM が返す抽出アイテム."""

    label: str = Field(
        description="項目名（日本語。部位・荷重種別・パラメータ名等を組み合わせる。"
        "例: '屋根 固定荷重', 'SN400B 降伏点'）"
    )
    value_type: Literal["numeric", "name", "formula"] = Field(
        description="値の種類（現時点では 'numeric' のみ対応）"
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
# ブロック構造モデル (Step 1 出力 / Step 3 入力)
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
