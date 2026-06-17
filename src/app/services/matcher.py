import re
from typing import cast, Any
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from langchain_core.prompts import ChatPromptTemplate
from app.db.models import CheckItem, SourceItem, MatchResult
from app.services.extractor import get_llm
from app.core.semaphores import get_llm_semaphore


class SingleMatchResponse(BaseModel):
    matched: bool = Field(description="一致する項目が候補リストに見つかったかどうか")
    matched_source_index: int | None = Field(
        None,
        description="一致した候補のインデックス番号 (0-indexed)。見つからなかった場合は None。",
    )
    confidence: float = Field(
        description="照合の信頼度スコア (0.0〜1.0)。数値・単位・部位が完全に一致すれば0.95以上。単位換算（例: N/m² と kN/m²）で一致すれば0.85〜0.94。数値が不一致や確証がない場合は0.80未満。"
    )
    ai_reasoning: str = Field(
        description="一致・不一致の判定理由。単位換算を行った場合はその計算過程を記述してください。"
    )


def token_overlap(s1: str, s2: str) -> float:
    tokens1 = set(re.findall(r"\w+", s1.lower()))
    tokens2 = set(re.findall(r"\w+", s2.lower()))
    if not tokens1 or not tokens2:
        return 0.0
    return len(tokens1.intersection(tokens2)) / len(tokens1.union(tokens2))


def _get_item_value_display(item: Any) -> str:
    """アイテムの value_type に応じた表示用文字列を返す."""
    vtype = getattr(item, "value_type", "numeric") or "numeric"
    if vtype == "numeric":
        val = cast(float, item.value) if item.value is not None else 0.0
        unit = cast(str, item.unit) if item.unit else ""
        return f"{val} {unit}".strip()
    elif vtype == "name":
        return str(item.text_value) if item.text_value else ""
    elif vtype == "formula":
        return str(item.formula_value) if item.formula_value else ""
    return ""


def calculate_candidate_score(check_item: CheckItem, item: SourceItem) -> float:
    check_vtype = (cast(str, check_item.value_type) if check_item.value_type else "numeric")
    item_vtype = (cast(str, item.value_type) if item.value_type else "numeric")

    num_score = 0.0

    if check_vtype == "numeric" and item_vtype == "numeric":
        val1 = cast(float, check_item.value) if check_item.value is not None else 0.0
        val2 = cast(float, item.value) if item.value is not None else 0.0
        if abs(val1 - val2) < 1e-5:
            num_score = 10.0
        elif abs(val1 * 1000.0 - val2) < 1e-5 or abs(val1 - val2 * 1000.0) < 1e-5:
            num_score = 8.0
    elif check_vtype == "name" and item_vtype == "name":
        check_text = str(check_item.text_value) if check_item.text_value else ""
        item_text = str(item.text_value) if item.text_value else ""
        if check_text and item_text:
            if check_text == item_text:
                num_score = 10.0
            elif check_text in item_text or item_text in check_text:
                num_score = 7.0
    elif check_vtype == item_vtype:
        # formula or other same-type match
        num_score = 3.0

    label_sim = token_overlap(cast(str, check_item.label), cast(str, item.label))
    context_sim = token_overlap(
        cast(str, check_item.context), cast(str, item.context_text)
    )
    text_score = label_sim * 4.0 + context_sim * 1.0

    hint_boost = 0.0
    if check_item.source_hint:
        hint_lower = cast(str, check_item.source_hint).lower()
        p_matches = re.findall(r"(?:p|page|ページ|頁)\.?\s*(\d+)", hint_lower)
        if p_matches:
            try:
                pages = [int(p) for p in p_matches]
                if cast(int, item.page) in pages:
                    hint_boost += 2.0
            except ValueError:
                pass

        hint_words = [
            w
            for w in re.findall(
                r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\w]+", hint_lower
            )
            if len(w) >= 2
        ]
        for hw in hint_words:
            if (
                hw in cast(str, item.context_text).lower()
                or hw in cast(str, item.label).lower()
            ):
                hint_boost += 1.0
                break

    return num_score + text_score + hint_boost


async def match_check_item(
    db: Session,
    check_item: CheckItem,
    document_ids: list[str] | None = None,
    llm: Any = None,
) -> MatchResult:
    query = db.query(SourceItem)
    if document_ids:
        query = query.filter(SourceItem.document_id.in_(document_ids))
    if check_item.category:
        query = query.filter(SourceItem.category == check_item.category)
    source_items = query.all()

    if not source_items:
        return MatchResult(
            check_item_id=check_item.id,
            source_item_id=None,
            confidence=0.0,
            status="pending",
            ai_reasoning="No reference items found in the database.",
        )

    candidates_with_scores = []
    for item in source_items:
        score = calculate_candidate_score(check_item, item)
        candidates_with_scores.append((score, item))

    candidates_with_scores.sort(key=lambda x: x[0], reverse=True)
    top_candidates = [item for _, item in candidates_with_scores[:5]]

    if llm is None:
        llm = get_llm()
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "あなたは建築構造設計の計算書（ファイルA）と、その出典となる荷重指針や法令（ファイルB）の数値を照合する専門家です。\n"
                    "ファイルAのチェック項目と、ファイルBから絞り込んだ「参照データ候補リスト」を照らし合わせ、同一の項目・数値であるかを判定してください。\n\n"
                    "【照合ルール】\n"
                    "1. 数値の比較: カンマの有無は無視して数値を比較します。\n"
                    "2. 単位変換: N/m² と kN/m² は 1,000倍 の関係にあります（例: 2,900 N/m² は 2.9 kN/m² と一致します）。単位変換して数値が一致した場合は matched: true、confidence: 0.90 程度とし、理由に単位換算した旨を記述してください。\n"
                    "3. 出典ヒントの活用: ファイルAの source_hint（例: '表4.1 ／ p.45', '令85条 表1'）と、ファイルB候補のページ番号や文脈を照らし合わせて、最も適切な参照データと結びつけてください。"
                ),
            ),
            (
                "user",
                (
                    "【ファイルA チェック項目】\n"
                    "項目名: {check_label}\n"
                    "数値: {check_value}\n"
                    "単位: {check_unit}\n"
                    "ページ番号: {check_page}\n"
                    "文脈: {check_context}\n"
                    "出典ヒント: {check_hint}\n\n"
                    "【ファイルB 参照データ候補リスト】\n"
                    "{candidates_str}\n\n"
                    "候補リストの中から一致するものを判定し、結果を構造化出力してください。"
                ),
            ),
        ]
    )

    candidates_formatted = []
    for idx, item in enumerate(top_candidates):
        value_display = _get_item_value_display(item)
        candidates_formatted.append(
            f"候補 [{idx}]:\n"
            f"  項目名: {cast(str, item.label)}\n"
            f"  値: {value_display}\n"
            f"  単位: {cast(str, item.unit) if item.unit else 'なし'}\n"
            f"  ページ番号: {cast(int, item.page)}\n"
            f"  文脈: {cast(str, item.context_text)}\n"
        )
    candidates_str = "\n".join(candidates_formatted)

    chain = prompt | llm.with_structured_output(SingleMatchResponse)

    check_value_display = _get_item_value_display(check_item)

    semaphore = get_llm_semaphore()
    try:
        async with semaphore:
            response = await chain.ainvoke(
                {
                    "check_label": cast(str, check_item.label),
                    "check_value": check_value_display,
                    "check_unit": cast(str, check_item.unit)
                    if check_item.unit
                    else "なし",
                    "check_page": cast(int, check_item.page),
                    "check_context": cast(str, check_item.context),
                    "check_hint": cast(str, check_item.source_hint)
                    if check_item.source_hint
                    else "なし",
                    "candidates_str": candidates_str,
                }
            )
    except Exception as e:
        return MatchResult(
            check_item_id=check_item.id,
            source_item_id=None,
            confidence=0.0,
            status="pending",
            ai_reasoning=f"LLM match check failed due to exception: {e}",
        )

    matched_item = None
    if response.matched and response.matched_source_index is not None:
        idx = response.matched_source_index
        if 0 <= idx < len(top_candidates):
            matched_item = top_candidates[idx]

    return MatchResult(
        check_item_id=check_item.id,
        source_item_id=str(matched_item.id) if matched_item else None,
        confidence=response.confidence,
        status="approved"
        if (response.matched and response.confidence >= 0.90)
        else "pending",
        ai_reasoning=response.ai_reasoning,
    )
