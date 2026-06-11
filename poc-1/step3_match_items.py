import json
import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

# Load environment
load_dotenv()

class MatchResult(BaseModel):
    check_item_label: str = Field(description="ファイルAの項目名")
    check_item_value: float = Field(description="ファイルAの数値")
    check_item_unit: str = Field(description="ファイルAの単位")
    check_item_page: int = Field(description="ファイルAのページ番号")
    
    matched: bool = Field(description="一致する項目がファイルBに見つかったかどうか")
    matched_source_label: str | None = Field(None, description="一致したファイルBの項目名（見つからなかった場合はNone）")
    matched_source_value: float | None = Field(None, description="一致したファイルBの数値（見つからなかった場合はNone）")
    matched_source_unit: str | None = Field(None, description="一致したファイルBの単位（見つからなかった場合はNone）")
    matched_source_page: int | None = Field(None, description="一致したファイルBのページ番号（見つからなかった場合はNone）")
    
    confidence: float = Field(description="照合の信頼度スコア (0.0〜1.0)。数値・単位・部位が一致すれば0.95以上。単位換算（1 kN/m² = 1000 N/m²）で一致すれば0.85〜0.94。数値が不一致や確証がない場合は0.80未満。")
    ai_reasoning: str = Field(description="一致・不一致の判定理由。単位換算を行った場合はその計算過程を記載。")

class MatchResultsList(BaseModel):
    results: list[MatchResult]

def get_llm():
    from langchain_google_genai import ChatGoogleGenerativeAI
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    primary_llm = ChatGoogleGenerativeAI(model=model, temperature=0.0)
    
    # Check if Azure OpenAI is configured for fallback
    azure_api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    azure_deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME")
    
    if azure_api_key and azure_endpoint:
        from langchain_openai import AzureChatOpenAI
        from pydantic import SecretStr
        azure_llm = AzureChatOpenAI(
            azure_deployment=azure_deployment,
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
            azure_endpoint=azure_endpoint,
            api_key=SecretStr(azure_api_key),
            temperature=0.0
        )
        return primary_llm.with_fallbacks([azure_llm])
        
    return primary_llm

def main() -> None:
    workspace_dir = Path("/Users/shotaro/work/markval")
    poc_data_dir = workspace_dir / "poc_data"
    
    # Load structured items
    with open(poc_data_dir / "poc1_structured_a.json", "r", encoding="utf-8") as f:
        data_a = json.load(f)
    with open(poc_data_dir / "poc1_structured_b.json", "r", encoding="utf-8") as f:
        data_b = json.load(f)
        
    items_a = data_a["items"]
    items_b = data_b["items"]

    # Initialize LLM
    llm = get_llm()

    # Create matching prompt
    prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "あなたは建築構造設計の計算書（ファイルA）と、その出典となる荷重指針や法令（ファイルB）の数値を照合する専門家です。\n"
            "ファイルAの各チェック項目について、ファイルBの参照データリストの中から一致するものを探し、照合結果を出力してください。\n\n"
            "【照合ルール】\n"
            "1. 数値の正規化: カンマの有無は無視して数値を比較します。\n"
            "2. 単位変換: N/m² と kN/m² は 1,000倍 の関係にあります（例: 2,900 N/m² は 2.9 kN/m² と一致します）。単位変換して一致した場合は matched: true、confidence: 0.90 程度とし、理由に単位換算した旨を記述してください。\n"
            "3. 出典ヒントの活用: ファイルAの source_hint（例: '表4.1 ／ p.45', '令85条 表1'）と、ファイルBのページ番号や項目名を照らし合わせて、最も適切な参照データと結びつけてください。"
        )),
        ("user", (
            "ファイルAのチェック項目リストと、ファイルBの参照データリストを以下に示します。照合を行ってください。\n\n"
            "【ファイルA チェック項目リスト】\n"
            "{items_a_str}\n\n"
            "【ファイルB 参照データリスト】\n"
            "{items_b_str}"
        ))
    ])

    # Format lists for LLM
    items_a_str = json.dumps(items_a, ensure_ascii=False, indent=2)
    items_b_str = json.dumps(items_b, ensure_ascii=False, indent=2)

    print("Matching checklist items against reference data...")
    chain = prompt | llm.with_structured_output(MatchResultsList)
    results = chain.invoke({
        "items_a_str": items_a_str,
        "items_b_str": items_b_str
    })

    output_file = poc_data_dir / "poc1_matched_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results.model_dump(), f, ensure_ascii=False, indent=2)
    print(f"Saved matching results to {output_file}")

if __name__ == "__main__":
    main()
