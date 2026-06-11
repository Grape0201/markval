import json
import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

# Load environment variables
load_dotenv()

# Page-level extraction schemas
class PageCheckItem(BaseModel):
    label: str = Field(description="項目名（日本語。部位・荷重種別・パラメータ名等を組み合わせる。例: '屋根 固定荷重', '事務室 積載荷重 (床用)', '標準せん断力係数 Co', 'SN400B 降伏点' など）")
    symbol: str | None = Field(None, description="記号（あれば。例: 'Co', 'Z', 'Rt', 'Ci', 'Vo', 'Gf', 'qp', 'Cf', 'ft' など）")
    value: float = Field(description="数値（実数型。例: 1200, 2.2, 0.20, 34, 0.256, 156）")
    unit: str = Field(description="単位（例: 'N/m²', 'N/mm²', 'm/s'。無単位の場合は '─' または None）")
    context: str = Field(description="抽出箇所の前後の文脈テキスト（表の周囲や該当行の文字列を含める）")
    source_hint: str | None = Field(None, description="計算書に記載されている出典情報・参照先（例: '表4.1 ／ p.45', '令85条 表1', '令88条第1項' など。ない場合はNone）")

class PageChecklist(BaseModel):
    items: list[PageCheckItem]

class PageSourceItem(BaseModel):
    label: str = Field(description="項目名（日本語。室用途や部材種別・パラメータ名、荷重区分を組み合わせる。例: '折板葺き（断熱材あり） 固定荷重', '事務室 積載荷重 (床用)', '地表面粗度区分Ⅲ Gf(H=10m)', '閉鎖型（矩形） 総合（壁面） Cf' など）")
    value: float = Field(description="数値")
    unit: str = Field(description="単位（例: 'N/m²', 'm/s', 'N/mm²'。無単位の場合は '─' または None）")
    context_text: str = Field(description="前後の文脈テキストや適用条件")

class PageSourceList(BaseModel):
    items: list[PageSourceItem]


# Schema for final output
class CheckItem(BaseModel):
    label: str
    symbol: str | None
    value: float
    unit: str
    page: int
    context: str
    source_hint: str | None

class SourceItem(BaseModel):
    label: str
    value: float
    unit: str
    page: int
    context_text: str


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
    
    # Load step 1 results
    with open(poc_data_dir / "poc1_extracted_a.json", "r", encoding="utf-8") as f:
        data_a = json.load(f)
    with open(poc_data_dir / "poc1_extracted_b.json", "r", encoding="utf-8") as f:
        data_b = json.load(f)

    # Initialize LLM
    llm = get_llm()

    # Process File A (Checklist)
    print("Extracting structured checklist items from File A page by page...")
    prompt_a = ChatPromptTemplate.from_messages([
        ("system", (
            "あなたは構造計算書（ファイルA）から設計に使用した荷重・定数の入力値を抽出する専門家です。\n"
            "入力されたページテキスト（Markdown形式）から、設計定数や設計荷重等の入力パラメータを抽出してください。\n\n"
            "【抽出対象】\n"
            "- 各部位の固定荷重（部位ごとの N/m² 値）\n"
            "- 積載荷重（室用途・加重種別（床用、大梁・柱用、地震用）ごとの N/m² 値）\n"
            "- 地震関連パラメータ（Co, Z, Rt, Ci 等の数値）\n"
            "- 風荷重パラメータ（Vo, Gf, qp, Cf 等の数値）\n"
            "- 材料強度（鋼材種別ごとの降伏点、引張強さ、長期許容応力度 ft の N/mm² 値）"
        )),
        ("user", (
            "以下のテキストから、設計に使用した荷重・定数の入力値を抽出してください。\n\n"
            "【対象テキスト】\n"
            "{text}"
        ))
    ])
    chain_a = prompt_a | llm.with_structured_output(PageChecklist)
    
    final_items_a = []
    for page_info in data_a["pages"]:
        page_num = page_info["page"]
        markdown_text = page_info["markdown"]
        print(f"Extracting File A Page {page_num}...")
        
        result = chain_a.invoke({"text": markdown_text})
        for item in result.items:
            final_items_a.append(CheckItem(
                label=item.label,
                symbol=item.symbol,
                value=item.value,
                unit=item.unit,
                page=page_num,
                context=item.context,
                source_hint=item.source_hint
            ))

    output_a = poc_data_dir / "poc1_structured_a.json"
    with open(output_a, "w", encoding="utf-8") as f:
        json.dump({"items": [item.model_dump() for item in final_items_a]}, f, ensure_ascii=False, indent=2)
    print(f"Saved File A structured items to {output_a}")

    # Process File B (Source references)
    print("Extracting structured reference items from File B page by page...")
    prompt_b = ChatPromptTemplate.from_messages([
        ("system", (
            "あなたは建築構造設計の基準書・荷重指針（ファイルB）から標準的な数値データを抽出する専門家です。\n"
            "入力されたページテキスト（Markdown形式）から、各部位の固定荷重標準値、積載荷重、風荷重などのデータを抽出してください。\n"
            "積載荷重は「床用」「大梁・柱用」「地震用」などの区分がある場合は、それぞれの数値を別々の項目として抽出してください（例: '事務室 積載荷重 (床用)', '事務室 積載荷重 (大梁・柱用)'）。"
        )),
        ("user", (
            "以下のテキストから、基準値やパラメータの数値を抽出してください。\n\n"
            "【対象テキスト】\n"
            "{text}"
        ))
    ])
    chain_b = prompt_b | llm.with_structured_output(PageSourceList)

    final_items_b = []
    for page_info in data_b["pages"]:
        page_num = page_info["page"]
        markdown_text = page_info["markdown"]
        print(f"Extracting File B Page {page_num}...")
        
        result = chain_b.invoke({"text": markdown_text})
        for item in result.items:
            final_items_b.append(SourceItem(
                label=item.label,
                value=item.value,
                unit=item.unit,
                page=page_num,
                context_text=item.context_text
            ))

    output_b = poc_data_dir / "poc1_structured_b.json"
    with open(output_b, "w", encoding="utf-8") as f:
        json.dump({"items": [item.model_dump() for item in final_items_b]}, f, ensure_ascii=False, indent=2)
    print(f"Saved File B structured references to {output_b}")

if __name__ == "__main__":
    main()
