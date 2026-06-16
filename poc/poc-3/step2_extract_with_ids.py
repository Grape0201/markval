"""Step 2: ブロック ID 付きテキストを LLM に入力し、構造化抽出を行う.

使い方:
    # プロンプトの生成のみ（LLM 呼び出しなし）
    uv run python step2_extract_with_ids.py --dry-run

    # LLM 呼び出しを実行（GOOGLE_API_KEY が必要）
    uv run python step2_extract_with_ids.py

    # LLM レスポンス JSON を手動で保存した場合の読み込み
    uv run python step2_extract_with_ids.py --load-responses
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from models import DocumentBlocks, ExtractedItem, PageExtraction

from dotenv import load_dotenv


load_dotenv()

# ---------------------------------------------------------------------------
# カテゴリリスト（本番と同一）
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
# プロンプトテンプレート
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
- context には、値が記載されている前後の文脈テキストを記入してください。

【カテゴリリスト】: {categories}
"""

USER_PROMPT = """\
以下のテキストから、設計パラメータを抽出してください。
数値だけでなく、種別・名称・区分などのテキスト型パラメータも抽出対象です。

【対象テキスト】
{text}
"""


# ---------------------------------------------------------------------------
# Prompt 構築
# ---------------------------------------------------------------------------


class PromptSet(BaseModel):
    """LLM に送るプロンプト一式."""

    system: str
    user: str
    page: int
    source: str


def build_prompts(doc: DocumentBlocks, file_type: str) -> list[PromptSet]:
    """ドキュメントの各ページについてプロンプトを構築する."""
    cats_str = ", ".join(DEFAULT_CATEGORIES)
    system_template = SYSTEM_PROMPT_A if file_type == "a" else SYSTEM_PROMPT_B
    system = system_template.format(categories=cats_str)

    prompts: list[PromptSet] = []
    for page in doc.pages:
        user = USER_PROMPT.format(text=page.formatted_text)
        prompts.append(
            PromptSet(
                system=system,
                user=user,
                page=page.page,
                source=doc.source,
            )
        )
    return prompts


# ---------------------------------------------------------------------------
# LLM 呼び出し
# ---------------------------------------------------------------------------


async def call_llm(prompt: PromptSet) -> PageExtraction:
    """LLM を呼び出して構造化抽出結果を取得する."""
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_google_genai import ChatGoogleGenerativeAI

    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    llm = ChatGoogleGenerativeAI(model=model_name, temperature=0.0)

    chat_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", prompt.system),
            ("user", "{text}"),
        ]
    )
    chain = chat_prompt | llm.with_structured_output(PageExtraction)
    result = await chain.ainvoke({"text": prompt.user})
    return result


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------


def save_prompts(prompts: list[PromptSet], output_dir: Path) -> None:
    """プロンプトをファイルに保存する（手動 LLM 呼び出し用）."""
    for p in prompts:
        file_type = p.source[0]  # 'a' or 'b'

        # システムプロンプト（ファイルタイプごとに 1 回だけ保存）
        sys_path = output_dir / f"poc3_system_prompt_{file_type}.txt"
        if not sys_path.exists():
            with sys_path.open("w") as f:
                f.write(p.system)

        # ユーザープロンプト（ページごと）
        user_path = output_dir / f"poc3_user_prompt_{file_type}_p{p.page}.txt"
        with user_path.open("w") as f:
            f.write(p.user)

    # JSON スキーマも保存（LLM の structured output 設定用）
    schema_path = output_dir / "poc3_extraction_schema.json"
    with schema_path.open("w") as f:
        json.dump(
            PageExtraction.model_json_schema(),
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"  📝 Prompts saved to {output_dir}/poc3_*_prompt_*.txt")
    print(f"  📝 Schema saved to {schema_path}")


def load_blocks(data_dir: Path, file_type: str) -> DocumentBlocks | None:
    """Step 1 の出力を読み込む."""
    path = data_dir / f"poc3_blocks_{file_type}.json"
    if not path.exists():
        print(f"⏭  Skipping {file_type}: {path} not found (run step1 first)")
        return None
    with path.open() as f:
        return DocumentBlocks.model_validate(json.load(f))


def save_extraction(
    results: dict[int, list[dict[str, Any]]],
    source: str,
    output_path: Path,
) -> None:
    """抽出結果を保存する."""
    output = {
        "source": source,
        "pages": [
            {"page": page_num, "items": items}
            for page_num, items in sorted(results.items())
        ],
    }
    with output_path.open("w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)


def load_responses(data_dir: Path, file_type: str) -> dict[int, PageExtraction]:
    """手動で保存された LLM レスポンス JSON を読み込む.

    期待するファイル: poc3_response_{file_type}_p{page}.json
    内容: PageExtraction の JSON（{"items": [...]}）
    """
    responses: dict[int, PageExtraction] = {}
    for path in sorted(data_dir.glob(f"poc3_response_{file_type}_p*.json")):
        page_str = path.stem.split("_p")[-1]
        page_num = int(page_str)
        with path.open() as f:
            data = json.load(f)
        responses[page_num] = PageExtraction.model_validate(data)
        print(f"  📥 Loaded response for page {page_num}: {len(responses[page_num].items)} items")
    return responses


async def run_llm_extraction(
    data_dir: Path, file_type: str
) -> None:
    """LLM を呼び出して抽出を実行する."""
    doc = load_blocks(data_dir, file_type)
    if doc is None:
        return

    prompts = build_prompts(doc, file_type)
    results: dict[int, list[dict[str, Any]]] = {}

    for prompt in prompts:
        print(f"  🤖 Calling LLM for page {prompt.page} ...")
        extraction = await call_llm(prompt)
        results[prompt.page] = [item.model_dump() for item in extraction.items]
        print(f"     → {len(extraction.items)} items extracted")

    output_path = data_dir / f"poc3_extracted_{file_type}.json"
    save_extraction(results, doc.source, output_path)
    print(f"  ✅ Saved to {output_path}")


def run_load_responses(data_dir: Path, file_type: str) -> None:
    """保存済み LLM レスポンスから抽出結果を構築する."""
    doc = load_blocks(data_dir, file_type)
    if doc is None:
        return

    responses = load_responses(data_dir, file_type)
    if not responses:
        print(f"  ⚠️  No response files found for {file_type}")
        print(f"     Expected: {data_dir}/poc3_response_{file_type}_p*.json")
        return

    results: dict[int, list[dict[str, Any]]] = {}
    for page_num, extraction in responses.items():
        results[page_num] = [item.model_dump() for item in extraction.items]

    output_path = data_dir / f"poc3_extracted_{file_type}.json"
    save_extraction(results, doc.source, output_path)
    print(f"  ✅ Saved to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Step 2: LLM extraction with block IDs")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="プロンプトの保存のみ。LLM 呼び出しを行わない。",
    )
    parser.add_argument(
        "--load-responses",
        action="store_true",
        help="poc3_response_{a,b}_p*.json からレスポンスを読み込む。",
    )
    parser.add_argument(
        "--file",
        choices=["a", "b", "both"],
        default="both",
        help="処理対象ファイル（default: both）",
    )
    args = parser.parse_args()

    data_dir = Path(__file__).resolve().parent.parent / "poc_data"
    file_types = ["a", "b"] if args.file == "both" else [args.file]

    for ft in file_types:
        doc = load_blocks(data_dir, ft)
        if doc is None:
            continue

        print(f"📄 Processing File {ft.upper()} ({doc.source}) ...")

        # プロンプトを常に保存
        prompts = build_prompts(doc, ft)
        save_prompts(prompts, data_dir)

        if args.dry_run:
            print("  🏃 Dry run — prompts saved, no LLM call.")
            for p in prompts:
                token_est = len(p.user) // 4  # 大雑把なトークン推定
                print(f"     Page {p.page}: ~{token_est} tokens (user prompt)")
        elif args.load_responses:
            run_load_responses(data_dir, ft)
        else:
            import asyncio
            asyncio.run(run_llm_extraction(data_dir, ft))

        print()


if __name__ == "__main__":
    main()
