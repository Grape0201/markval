import json
import re
from pathlib import Path
import pdfplumber

def clean_and_parse_value(text: str) -> float | None:
    text = text.strip()
    # Stricter pattern: allow digits, commas, a single dot, and optional minus sign.
    # No alphabetic characters or special symbols are allowed.
    if not re.match(r"^-?[0-9,]+(\.[0-9]+)?$", text):
        return None
    cleaned = text.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None

def extract_bboxes_for_file(pdf_path: Path, structured_json_path: Path, output_json_path: Path) -> None:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    if not structured_json_path.exists():
        raise FileNotFoundError(f"Structured JSON not found: {structured_json_path}")
        
    print(f"\n--- Extracting Bboxes for {pdf_path.name} ---")
    
    with open(structured_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data["items"]
    
    updated_items = []
    
    with pdfplumber.open(pdf_path) as pdf:
        for item in items:
            label = item["label"]
            target_value = item["value"]
            page_num = item["page"]
            # File A uses "context", File B uses "context_text"
            context = item.get("context") or item.get("context_text") or ""
            
            if page_num < 1 or page_num > len(pdf.pages):
                print(f"⚠️ Page number {page_num} is out of range for the PDF (total pages: {len(pdf.pages)})")
                item["bbox"] = None
                updated_items.append(item)
                continue
                
            page = pdf.pages[page_num - 1]
            words = page.extract_words()
            
            # Group words to lines for context comparison
            words_sorted = sorted(words, key=lambda w: (w["top"], w["x0"]))
            lines: list[list[dict]] = []
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
                print(f"❌ Could not find value {target_value} on page {page_num} for label '{label}'")
                item["bbox"] = None
                updated_items.append(item)
                continue
            
            # Disambiguate candidates using keyword token intersection
            best_word = None
            best_score = -1.0
            
            # Extract keywords from the label and context
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
                print(f"   Matched: '{label}' -> Bbox: {bbox} on Page {page_num}")
            else:
                print(f"❌ Failed to disambiguate candidates for label '{label}' on Page {page_num}")
                item["bbox"] = None
                
            updated_items.append(item)

    # Save output
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump({"items": updated_items}, f, ensure_ascii=False, indent=2)
    print(f"Saved structured items with bboxes to {output_json_path}")

def main() -> None:
    workspace_dir = Path("/Users/shotaro/work/markval")
    poc_data_dir = workspace_dir / "poc_data"
    bench_dir = workspace_dir / "bench"
    
    # Process File A
    file_a_pdf = bench_dir / "sample_file_a_keisan.pdf"
    file_a_json = poc_data_dir / "poc1_structured_a.json"
    file_a_out = poc_data_dir / "poc2_structured_a_with_bboxes.json"
    extract_bboxes_for_file(file_a_pdf, file_a_json, file_a_out)
    
    # Process File B
    file_b_pdf = bench_dir / "sample_file_b_kajushishin.pdf"
    file_b_json = poc_data_dir / "poc1_structured_b.json"
    file_b_out = poc_data_dir / "poc2_structured_b_with_bboxes.json"
    extract_bboxes_for_file(file_b_pdf, file_b_json, file_b_out)

if __name__ == "__main__":
    main()
