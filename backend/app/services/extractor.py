import io
import os
import re
from pathlib import Path
from pydantic import BaseModel, Field
from pypdf import PdfReader, PdfWriter
from markitdown import MarkItDown
import pdfplumber
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

# Pydantic schemas for File A (Checklist) structured extraction
class PageCheckItem(BaseModel):
    label: str = Field(description="項目名（日本語。部位・荷重種別・パラメータ名等を組み合わせる。例: '屋根 固定荷重', '事務室 積載荷重 (床用)', '標準せん断力係数 Co', 'SN400B 降伏点' など）")
    symbol: str | None = Field(None, description="記号（あれば。例: 'Co', 'Z', 'Rt', 'Ci', 'Vo', 'Gf', 'qp', 'Cf', 'ft' など）")
    value: float = Field(description="数値（実数型。例: 1200, 2.2, 0.20, 34, 0.256, 156）")
    unit: str = Field(description="単位（例: 'N/m²', 'N/mm²', 'm/s'。無単位の場合は '─' または None）")
    context: str = Field(description="抽出箇所の前後の文脈テキスト（表の周囲や該当行の文字列を含める）")
    source_hint: str | None = Field(None, description="計算書に記載されている出典情報・参照先（例: '表4.1 ／ p.45', '令85条 表1', '令88条第1項' など。ない場合はNone）")

class PageChecklist(BaseModel):
    items: list[PageCheckItem]

# Pydantic schemas for File B (Source Reference) structured extraction
class PageSourceItem(BaseModel):
    label: str = Field(description="項目名（日本語。室用途や部材種別・パラメータ名、荷重区分を組み合わせる。例: '折板葺き（断熱材あり） 固定荷重', '事務室 積載荷重 (床用)', '地表面粗度区分Ⅲ Gf(H=10m)', '閉鎖型（矩形） 総合（壁面） Cf' など）")
    value: float = Field(description="数値")
    unit: str = Field(description="単位（例: 'N/m²', 'm/s', 'N/mm²'。無単位の場合は '─' または None）")
    context_text: str = Field(description="前後の文脈テキストや適用条件")

class PageSourceList(BaseModel):
    items: list[PageSourceItem]


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
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
            azure_endpoint=azure_endpoint,
            api_key=SecretStr(azure_api_key),
            temperature=0.0
        )
        return primary_llm.with_fallbacks([azure_llm])
        
    return primary_llm


def generate_embeddings(texts: list[str]) -> list[None]:
    return [None for _ in texts]


def extract_pdf_to_markdown_pages(pdf_path: Path) -> list[dict]:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    reader = PdfReader(pdf_path)
    markitdown_converter = MarkItDown()
    pages_data = []

    for idx in range(len(reader.pages)):
        page_num = idx + 1
        
        # Write single page to a BytesIO stream
        writer = PdfWriter()
        writer.add_page(reader.pages[idx])
        
        pdf_stream = io.BytesIO()
        writer.write(pdf_stream)
        pdf_stream.seek(0)
        
        # Convert page to markdown
        result = markitdown_converter.convert_stream(pdf_stream, mime_type="application/pdf")
        markdown_text = result.text_content
        
        pages_data.append({
            "page": page_num,
            "markdown": markdown_text
        })

    return pages_data


def clean_and_parse_value(text: str) -> float | None:
    text = text.strip()
    if not re.match(r"^-?[0-9,]+(\.[0-9]+)?$", text):
        return None
    cleaned = text.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def find_bboxes_for_items(pdf_path: Path, items: list[dict]) -> list[dict]:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    updated_items = []
    
    with pdfplumber.open(pdf_path) as pdf:
        for item in items:
            label = item["label"]
            target_value = item["value"]
            page_num = item["page"]
            context = item.get("context") or item.get("context_text") or ""
            
            if page_num < 1 or page_num > len(pdf.pages):
                item["bbox"] = None
                updated_items.append(item)
                continue
                
            page = pdf.pages[page_num - 1]
            words = page.extract_words()
            
            # Group words to lines for context comparison
            words_sorted = sorted(words, key=lambda w: (w["top"], w["x0"]))
            lines = []
            if words_sorted:
                current_group = [words_sorted[0]]
                for w in words_sorted[1:]:
                    avg_top = sum(item["top"] for item in current_group) / len(current_group)
                    if abs(w["top"] - avg_top) < 3.0:
                        current_group.append(w)
                    else:
                        lines.append(current_group)
                        current_group = [w]
                lines.append(current_group)
            
            line_texts = []
            line_mappings = []
            for line in lines:
                line_words_sorted = sorted(line, key=lambda w: w["x0"])
                text = " ".join(w["text"] for w in line_words_sorted)
                line_texts.append(text)
                line_mappings.append(line_words_sorted)
                
            # Find candidate words representing target_value
            candidates = []
            for line_idx, line_words in enumerate(line_mappings):
                for word in line_words:
                    word_val = clean_and_parse_value(word["text"])
                    if word_val is not None and abs(word_val - target_value) < 1e-5:
                        candidates.append((word, line_texts[line_idx]))
            
            if not candidates:
                item["bbox"] = None
                updated_items.append(item)
                continue
            
            # Disambiguate candidates using token intersection
            best_word = None
            best_score = -1.0
            keywords = set(re.findall(r"\w+", label) + re.findall(r"\w+", context))
            
            for word, line_text in candidates:
                line_tokens = set(re.findall(r"\w+", line_text))
                matches = len(keywords.intersection(line_tokens))
                score = float(matches)
                if score > best_score:
                    best_score = score
                    best_word = word
            
            if best_word:
                bbox = {
                    "x0": round(float(best_word["x0"]), 1),
                    "y0": round(float(best_word["top"]), 1),
                    "x1": round(float(best_word["x1"]), 1),
                    "y1": round(float(best_word["bottom"]), 1)
                }
                item["bbox"] = bbox
            else:
                item["bbox"] = None
                
            updated_items.append(item)
            
    return updated_items


def extract_source_items_from_pdf(pdf_path: Path) -> list[dict]:
    pages_data = extract_pdf_to_markdown_pages(pdf_path)
    llm = get_llm()

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

    extracted_items = []
    for page_info in pages_data:
        page_num = page_info["page"]
        markdown_text = page_info["markdown"]
        
        result = chain_b.invoke({"text": markdown_text})
        for item in result.items:
            extracted_items.append({
                "page": page_num,
                "label": item.label,
                "value": item.value,
                "unit": item.unit,
                "context_text": item.context_text
            })

    # Localize bounding boxes using pdfplumber alignment
    items_with_bboxes = find_bboxes_for_items(pdf_path, extracted_items)
    
    # Compute embeddings in batch
    texts_to_embed = [f"{item['label']} | context: {item['context_text']}" for item in items_with_bboxes]
    embeddings = generate_embeddings(texts_to_embed)
    
    for item, emb in zip(items_with_bboxes, embeddings):
        item["embedding"] = emb

    return items_with_bboxes


def extract_check_items_from_pdf(pdf_path: Path) -> list[dict]:
    pages_data = extract_pdf_to_markdown_pages(pdf_path)
    llm = get_llm()

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

    extracted_items = []
    for page_info in pages_data:
        page_num = page_info["page"]
        markdown_text = page_info["markdown"]
        
        result = chain_a.invoke({"text": markdown_text})
        for item in result.items:
            extracted_items.append({
                "page": page_num,
                "label": item.label,
                "value": item.value,
                "unit": item.unit,
                "context": item.context,
                "source_hint": item.source_hint
            })

    # Localize bounding boxes using pdfplumber alignment
    items_with_bboxes = find_bboxes_for_items(pdf_path, extracted_items)
    return items_with_bboxes
