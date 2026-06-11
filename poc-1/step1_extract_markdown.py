import io
import json
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from markitdown import MarkItDown

def extract_pdf_to_markdown_pages(pdf_path: Path) -> dict:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    reader = PdfReader(pdf_path)
    markitdown_converter = MarkItDown()
    pages_data = []

    print(f"Converting {pdf_path.name} to Markdown page by page...")
    for idx in range(len(reader.pages)):
        page_num = idx + 1
        print(f"Processing Page {page_num}...")
        
        # Write single page to a BytesIO stream
        writer = PdfWriter()
        writer.add_page(reader.pages[idx])
        
        pdf_stream = io.BytesIO()
        writer.write(pdf_stream)
        pdf_stream.seek(0)
        
        # Convert the single-page PDF stream to markdown
        result = markitdown_converter.convert_stream(pdf_stream, mime_type="application/pdf")
        markdown_text = result.text_content
        
        pages_data.append({
            "page": page_num,
            "markdown": markdown_text
        })

    return {
        "filename": pdf_path.name,
        "pages": pages_data
    }

def main() -> None:
    workspace_dir = Path("/Users/shotaro/work/markval")
    bench_dir = workspace_dir / "bench"
    poc_data_dir = workspace_dir / "poc_data"
    
    poc_data_dir.mkdir(exist_ok=True)
    
    # Process File A
    file_a_path = bench_dir / "sample_file_a_keisan.pdf"
    data_a = extract_pdf_to_markdown_pages(file_a_path)
    output_a = poc_data_dir / "poc1_extracted_a.json"
    with open(output_a, "w", encoding="utf-8") as f:
        json.dump(data_a, f, ensure_ascii=False, indent=2)
    print(f"Saved extracted File A to {output_a}")

    # Process File B
    file_b_path = bench_dir / "sample_file_b_kajushishin.pdf"
    data_b = extract_pdf_to_markdown_pages(file_b_path)
    output_b = poc_data_dir / "poc1_extracted_b.json"
    with open(output_b, "w", encoding="utf-8") as f:
        json.dump(data_b, f, ensure_ascii=False, indent=2)
    print(f"Saved extracted File B to {output_b}")

if __name__ == "__main__":
    main()
