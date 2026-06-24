import json
from pathlib import Path
from typing import Any
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Highlight
from pypdf.generic import ArrayObject, FloatObject

# Yomitoku OCR は 200 DPI で画像化して認識するため、
# PDF ポイント座標系 (72 DPI) への変換係数は 72 / 200 = 0.36
SCALE_FACTOR = 72.0 / 200.0

def annotate_pdf_file_b(
    pdf_path: Path,
    resolved_items: list[dict[str, Any]],
    output_pdf_path: Path
) -> None:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    reader = PdfReader(pdf_path)
    writer = PdfWriter()

    # ページごとにアノテーションをグループ化
    page_modifications: dict[int, list[dict[str, Any]]] = {}
    for item in resolved_items:
        # bbox が存在しない場合はスキップ
        if not item.get("bbox"):
            continue
        page_num = int(item["page"])
        page_modifications.setdefault(page_num, []).append(item)

    # 各ページを処理
    for i in range(len(reader.pages)):
        page_num = i + 1
        page = reader.pages[i]
        
        # ページを writer に追加
        writer.add_page(page)
        
        if page_num in page_modifications:
            print(f"Drawing annotations on File B Page {page_num}...")
            height = float(page.mediabox.height)
            
            for item in page_modifications[page_num]:
                bbox = item["bbox"]  # [x0, y0, x1, y1] (Yomitoku pixel 座標)
                
                # スケーリング (pixel -> point)
                x0 = bbox[0] * SCALE_FACTOR
                y0 = bbox[1] * SCALE_FACTOR
                x1 = bbox[2] * SCALE_FACTOR
                y1 = bbox[3] * SCALE_FACTOR
                
                # PDF 座標系 (左下原点) への変換
                rx0 = x0
                rx1 = x1
                ry0 = height - y1
                ry1 = height - y0
                
                # QuadPoints: top-left, top-right, bottom-left, bottom-right
                quads = [rx0, ry1, rx1, ry1, rx0, ry0, rx1, ry0]
                
                rect = (rx0, ry0, rx1, ry1)
                
                # HighlightAnnotationの作成 (薄いオレンジ/イエローのハイライトのみ)
                highlight = Highlight(
                    rect=rect,
                    quad_points=ArrayObject([FloatObject(x) for x in quads]),
                    highlight_color="ffe599"
                )
                
                # アノテーションを追加
                writer.add_annotation(page_number=i, annotation=highlight)

    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_pdf_path, "wb") as f_out:
        writer.write(f_out)
    print(f"Saved annotated File B PDF to {output_pdf_path}")

def main() -> None:
    workspace_dir = Path(__file__).resolve().parents[2]
    poc_data_dir = workspace_dir / "poc" / "poc_data"
    bench_dir = workspace_dir / "bench"
    
    resolved_b_path = poc_data_dir / "poc3_resolved_b.json"
    if not resolved_b_path.exists():
        raise FileNotFoundError(f"Resolved B file not found: {resolved_b_path}. Please run step3 first.")
        
    with open(resolved_b_path, "r", encoding="utf-8") as f:
        resolved_data = json.load(f)
        
    # 各ページのアイテムをフラットにし、本番の annotator.py 互換のデータ構造に変換する
    resolved_items = []
    for page_data in resolved_data.get("pages", []):
        page_num = page_data["page"]
        for item in page_data.get("items", []):
            val_type = item.get("value_type", "numeric")
            # value_type に応じて値を "value" キーにマッピング
            val = item.get("text_value") if val_type == "name" else item.get("numeric_value")
            
            mapped_item = {
                "page": page_num,
                "label": item.get("label", ""),
                "value": val,
                "unit": item.get("unit", "") or "",
                "category": item.get("category", ""),
                "context_text": item.get("context", ""),
                "bbox": item.get("bbox"),
                "source_block_ids": item.get("source_block_ids", [])
            }
            resolved_items.append(mapped_item)
        
    file_b_pdf = bench_dir / "sample_file_b_kajushishin.pdf"
    output_pdf_path = poc_data_dir / "poc3_annotated_file_b.pdf"
    
    annotate_pdf_file_b(file_b_pdf, resolved_items, output_pdf_path)

if __name__ == "__main__":
    main()
