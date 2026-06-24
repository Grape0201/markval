"""抽出サービス: OCR → ブロック構築 → LLM 構造化抽出 → Bbox 解決.

PoC-3 のブロック ID 参照方式を本番パイプラインに統合。
LLM には OCR ブロックの ID 付きテキストを入力し、
抽出結果にブロック ID を含めて返させる。
Bbox はブロック ID から解決する（Phase 1: ブロック Bbox, Phase 2: Word 精密検索）。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from app.core.semaphores import get_llm_semaphore
from app.services.block_builder import (
    build_document_blocks,
)
from app.services.bbox_resolver import resolve_all_bboxes
from app.services.document_providers import OCRProvider, YomitokuProvider


# ---------------------------------------------------------------------------
# Pydantic schemas for LLM structured output (File A: Checklist)
# ---------------------------------------------------------------------------


class PageCheckItem(BaseModel):
    label: str = Field(
        description="項目名（日本語。部位・荷重種別・パラメータ名等を組み合わせる。例: '屋根 固定荷重', '事務室 積載荷重 (床用)', '標準せん断力係数 Co', 'SN400B 降伏点' など）"
    )
    value_type: str = Field(
        description="値の種類。'numeric' / 'name' / 'formula' のいずれか。"
    )
    numeric_value: float | None = Field(
        None,
        description="数値（value_type='numeric' の場合。例: 1200, 0.20）",
    )
    text_value: str | None = Field(
        None,
        description="名称やテキスト値（value_type='name' の場合。例: '第二種', 'SN400B'）",
    )
    formula_value: str | None = Field(
        None,
        description="数式（value_type='formula' の場合。LaTeX 形式推奨）",
    )
    unit: str | None = Field(
        None,
        description="単位（例: 'N/m²', 'N/mm²', 'm/s'。無単位の場合は None）",
    )
    context: str = Field(
        description="抽出箇所の前後の文脈テキスト（表の周囲や該当行の文字列を含める）"
    )
    source_hint: str | None = Field(
        None,
        description="計算書に記載されている出典情報・参照先（例: '表4.1 ／ p.45', '令85条 表1', '令88条第1項' など。ない場合はNone）",
    )
    source_block_ids: list[str] = Field(
        description="抽出の根拠となったブロック ID リスト（例: ['T001-R2']）。"
        "与えられた ID の中から選択すること。存在しない ID を生成しないこと。",
    )
    category: str = Field(
        description="分類カテゴリ。指定された候補の中から最もふさわしいものを1つ選んで設定してください。"
    )


class PageChecklist(BaseModel):
    items: list[PageCheckItem]


# ---------------------------------------------------------------------------
# Pydantic schemas for LLM structured output (File B: Source Reference)
# ---------------------------------------------------------------------------


class PageSourceItem(BaseModel):
    label: str = Field(
        description="項目名（日本語。室用途や部材種別・パラメータ名、荷重区分を組み合わせる。例: '折板葺き（断熱材あり） 固定荷重', '事務室 積載荷重 (床用)', '地表面粗度区分Ⅲ Gf(H=10m)', '閉鎖型（矩形） 総合（壁面） Cf' など）"
    )
    value_type: str = Field(
        description="値の種類。'numeric' / 'name' / 'formula' のいずれか。"
    )
    numeric_value: float | None = Field(
        None,
        description="数値（value_type='numeric' の場合）",
    )
    text_value: str | None = Field(
        None,
        description="名称やテキスト値（value_type='name' の場合）",
    )
    formula_value: str | None = Field(
        None,
        description="数式（value_type='formula' の場合）",
    )
    unit: str | None = Field(
        None,
        description="単位（例: 'N/m²', 'm/s', 'N/mm²'。無単位の場合は None）",
    )
    context_text: str = Field(description="前後の文脈テキストや適用条件")
    source_block_ids: list[str] = Field(
        description="抽出の根拠となったブロック ID リスト。"
        "与えられた ID の中から選択すること。存在しない ID を生成しないこと。",
    )
    category: str = Field(
        description="分類カテゴリ。指定された候補の中から最もふさわしいものを1つ選んで設定してください。"
    )


class PageSourceList(BaseModel):
    items: list[PageSourceItem]


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------


def get_llm():
    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    primary_llm = ChatGoogleGenerativeAI(model=model_name, temperature=0.0)

    azure_api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    azure_deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME")

    if azure_api_key and azure_endpoint:
        from langchain_openai import AzureChatOpenAI
        from pydantic import SecretStr

        azure_llm = AzureChatOpenAI(
            azure_deployment=azure_deployment,
            api_version=os.environ.get(
                "AZURE_OPENAI_API_VERSION", "2024-02-15-preview"
            ),
            azure_endpoint=azure_endpoint,
            api_key=SecretStr(azure_api_key),
            temperature=0.0,
        )
        return primary_llm.with_fallbacks([azure_llm])

    return primary_llm


# ---------------------------------------------------------------------------
# OCR provider factory
# ---------------------------------------------------------------------------


def _get_ocr_provider() -> OCRProvider:
    return YomitokuProvider()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CATEGORIES = [
    "固定荷重",
    "積載荷重",
    "積雪荷重",
    "風荷重",
    "地震荷重",
    "材料強度",
    "その他",
]

# ---------------------------------------------------------------------------
# System prompts (PoC-3 block ID approach)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_A = """\
あなたは構造計算書（ファイルA）から設計に使用した荷重・定数の入力値を抽出する専門家です。

入力テキストは OCR 結果をブロック単位で ID 付きで提供しています。

【入力フォーマット】
- [B001/paragraph] テキスト ... → 段落テキスト（ID: B001）
- [T001-R1] | セル1 | セル2 | ... → テーブル行（ID: T001-R1）

【抽出対象】
- 各部位の固定荷重（部位ごとの N/m² 値）
- 積載荷重（室用途・加重種別（床用、大梁・柱用、地震用）ごとの N/m² 値）
- 地震関連パラメータ（Co, Z, Rt, Ci 等の数値）
- 風荷重パラメータ（Vo, Gf, qp, Cf 等の数値）
- 材料強度（鋼材種別ごとの降伏点、引張強さ、長期許容応力度 ft の N/mm² 値）
- 地盤種別・構造種別・材料名称などのテキスト型パラメータ（例: 第二種, 地表面粗度区分III, SN400B 等）

【value_type の使い分け】
- "numeric": 数値で表されるパラメータ（荷重値、係数、強度 等）→ numeric_value に数値を設定
- "name": 種別・名称・区分などテキストで表されるパラメータ（地盤種別「第二種」、粗度区分「III」等）→ text_value にテキストを設定
- "formula": 数式（現時点では未使用）

【重要ルール】
- source_block_ids には、抽出した値が記載されているブロックの ID を正確に記入してください。
- 与えられた ID の中から選択してください。存在しない ID を生成しないでください。
- 1つの項目が複数のブロックにまたがる場合は、関連する全ての ID をリストに含めてください。
- context には、値が記載されている前後の文脈テキストを記入してください。

【カテゴリリスト】: {categories}
"""

SYSTEM_PROMPT_B = """\
あなたは建築構造設計の基準書・荷重指針（ファイルB）から標準的なデータを抽出する専門家です。

入力テキストは OCR 結果をブロック単位で ID 付きで提供しています。

【入力フォーマット】
- [B001/paragraph] テキスト ... → 段落テキスト（ID: B001）
- [T001-R1] | セル1 | セル2 | ... → テーブル行（ID: T001-R1）

【抽出対象】
- 各部位の固定荷重標準値、積載荷重、風荷重などの数値データ
- 積載荷重は「床用」「大梁・柱用」「地震用」などの区分がある場合は、それぞれの数値を別々の項目として抽出してください
- 地盤種別・粗度区分・材料名称などのテキスト型パラメータ

【value_type の使い分け】
- "numeric": 数値で表されるパラメータ（荷重値、係数、強度 等）→ numeric_value に数値を設定
- "name": 種別・名称・区分などテキストで表されるパラメータ → text_value にテキストを設定
- "formula": 数式（現時点では未使用）

【重要ルール】
- source_block_ids には、抽出した値が記載されているブロックの ID を正確に記入してください。
- 与えられた ID の中から選択してください。存在しない ID を生成しないでください。
- 1つの項目が複数のブロックにまたがる場合は、関連する全ての ID をリストに含めてください。
- context_text には、値が記載されている前後の文脈テキストを記入してください。

【カテゴリリスト】: {categories}
"""

USER_PROMPT = """\
以下のテキストから、設計パラメータを抽出してください。
数値だけでなく、種別・名称・区分などのテキスト型パラメータも抽出対象です。

【対象テキスト】
{text}
"""


# ---------------------------------------------------------------------------
# Helper: get display value from multi-type item
# ---------------------------------------------------------------------------


def get_display_value(item: dict[str, Any]) -> str:
    """アイテムの value_type に応じた表示用文字列を返す."""
    vtype = item.get("value_type", "numeric")
    if vtype == "numeric":
        val = item.get("value") or item.get("numeric_value")
        unit = item.get("unit") or ""
        if val is not None:
            return f"{val} {unit}".strip()
        return ""
    elif vtype == "name":
        return item.get("text_value") or ""
    elif vtype == "formula":
        return item.get("formula_value") or ""
    return ""


# ---------------------------------------------------------------------------
# Extraction pipelines
# ---------------------------------------------------------------------------


async def extract_source_items_from_pdf(
    pdf_path: Path, categories: list[str] | None = None, llm: Any = None
) -> list[dict[str, Any]]:
    """File B（出典文書）から構造化データを抽出する."""
    provider = _get_ocr_provider()

    # 1. OCR
    await provider.ocr_pdf(pdf_path)
    ocr_pages = provider.get_ocr_pages()

    # 2. ブロック構築
    doc_blocks = build_document_blocks(ocr_pages, source=pdf_path.name)

    # 3. LLM 抽出
    if llm is None:
        llm = get_llm()

    cats = categories or DEFAULT_CATEGORIES
    cats_str = ", ".join(cats)
    system = SYSTEM_PROMPT_B.format(categories=cats_str)

    prompt_b = ChatPromptTemplate.from_messages(
        [
            ("system", system),
            ("user", USER_PROMPT),
        ]
    )
    chain_b = prompt_b | llm.with_structured_output(PageSourceList)
    semaphore = get_llm_semaphore()

    async def _extract_page(page_blocks: Any) -> list[dict[str, Any]]:
        page_num = page_blocks.page
        text = page_blocks.formatted_text
        if not text.strip():
            return []

        async with semaphore:
            result = await chain_b.ainvoke({"text": text})

        page_items = []
        for item in result.items:
            page_items.append(
                {
                    "page": page_num,
                    "label": item.label,
                    "value_type": item.value_type,
                    "value": item.numeric_value,
                    "numeric_value": item.numeric_value,
                    "text_value": item.text_value,
                    "formula_value": item.formula_value,
                    "unit": item.unit,
                    "context_text": item.context_text,
                    "source_block_ids": item.source_block_ids,
                    "category": item.category,
                }
            )
        return page_items

    tasks = [_extract_page(pb) for pb in doc_blocks.pages]
    pages_results = await asyncio.gather(*tasks)

    extracted_items: list[dict[str, Any]] = []
    for page_items in pages_results:
        extracted_items.extend(page_items)

    # 4. Bbox 解決
    items_with_bboxes = resolve_all_bboxes(extracted_items, doc_blocks)

    return items_with_bboxes


async def extract_check_items_from_pdf(
    pdf_path: Path, categories: list[str] | None = None, llm: Any = None
) -> list[dict[str, Any]]:
    """File A（構造計算書）から設計パラメータを抽出する."""
    provider = _get_ocr_provider()

    # 1. OCR
    await provider.ocr_pdf(pdf_path)
    ocr_pages = provider.get_ocr_pages()

    # 2. ブロック構築
    doc_blocks = build_document_blocks(ocr_pages, source=pdf_path.name)

    # 3. LLM 抽出
    if llm is None:
        llm = get_llm()

    cats = categories or DEFAULT_CATEGORIES
    cats_str = ", ".join(cats)
    system = SYSTEM_PROMPT_A.format(categories=cats_str)

    prompt_a = ChatPromptTemplate.from_messages(
        [
            ("system", system),
            ("user", USER_PROMPT),
        ]
    )
    chain_a = prompt_a | llm.with_structured_output(PageChecklist)
    semaphore = get_llm_semaphore()

    async def _extract_page(page_blocks: Any) -> list[dict[str, Any]]:
        page_num = page_blocks.page
        text = page_blocks.formatted_text
        if not text.strip():
            return []

        async with semaphore:
            result = await chain_a.ainvoke({"text": text})

        page_items = []
        for item in result.items:
            page_items.append(
                {
                    "page": page_num,
                    "label": item.label,
                    "value_type": item.value_type,
                    "value": item.numeric_value,
                    "numeric_value": item.numeric_value,
                    "text_value": item.text_value,
                    "formula_value": item.formula_value,
                    "unit": item.unit,
                    "context": item.context,
                    "source_hint": item.source_hint,
                    "source_block_ids": item.source_block_ids,
                    "category": item.category,
                }
            )
        return page_items

    tasks = [_extract_page(pb) for pb in doc_blocks.pages]
    pages_results = await asyncio.gather(*tasks)

    extracted_items: list[dict[str, Any]] = []
    for page_items in pages_results:
        extracted_items.extend(page_items)

    # 4. Bbox 解決
    items_with_bboxes = resolve_all_bboxes(extracted_items, doc_blocks)

    return items_with_bboxes
