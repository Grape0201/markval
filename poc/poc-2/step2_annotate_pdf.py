import io
import json
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfdoc import HighlightAnnotation

def draw_warning_mark(can: canvas.Canvas, cx: float, cy: float) -> None:
    # Draw warning triangle (⚠️) in orange/yellow
    # Width: 10pt (cx-5 to cx+5), Height: 8pt (cy to cy+8)
    can.setStrokeColorRGB(0.8, 0.4, 0.0)  # Dark orange outline
    can.setFillColorRGB(1.0, 0.75, 0.0)    # Yellow/orange fill
    can.setLineWidth(1.0)
    p = can.beginPath()
    p.moveTo(cx, cy + 8)          # Top
    p.lineTo(cx - 5, cy)          # Bottom left
    p.lineTo(cx + 5, cy)          # Bottom right
    p.close()
    can.drawPath(p, stroke=True, fill=True)
    
    # Exclamation point (!) inside the triangle
    can.setStrokeColorRGB(0.0, 0.0, 0.0)
    can.setLineWidth(1.0)
    can.line(cx, cy + 5.5, cx, cy + 2.5)  # Vertical bar
    
    can.setFillColorRGB(0.0, 0.0, 0.0)
    can.rect(cx - 0.5, cy + 0.8, 1.0, 1.0, stroke=0, fill=1)  # Dot

def annotate_pdf_file_a(
    pdf_path: Path,
    items_a: dict[str, dict],
    matched_data: dict,
    matched_ids: dict[str, str],
    output_pdf_path: Path
) -> None:
    reader = PdfReader(pdf_path)
    writer = PdfWriter()

    # Map page number (1-indexed) to list of annotations/drawings to make
    page_modifications: dict[int, list[tuple[dict, bool, dict | None]]] = {}
    
    for result in matched_data["results"]:
        label = result["check_item_label"]
        if label not in items_a:
            continue
        orig_item = items_a[label]
        page_num = orig_item["page"]
        
        if page_num not in page_modifications:
            page_modifications[page_num] = []
            
        page_modifications[page_num].append((orig_item, result["matched"], result))

    # Process each page
    for i in range(len(reader.pages)):
        page_num = i + 1
        page = reader.pages[i]
        
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        
        if page_num in page_modifications:
            print(f"Drawing annotations on File A Page {page_num}...")
            packet = io.BytesIO()
            can = canvas.Canvas(packet, pagesize=(width, height))
            
            for orig_item, is_matched, result in page_modifications[page_num]:
                bbox = orig_item.get("bbox")
                if not bbox:
                    status_type = "matched" if is_matched else "unmatched"
                    print(f"⚠️ Skipping {status_type} annotation for label '{orig_item['label']}' (Bbox was not found)")
                    continue
                    
                x0, y0, x1, y1 = bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"]
                
                # Coordinate translation from top-left (pdfplumber) to bottom-left (reportlab/PDF)
                rx0 = x0
                rx1 = x1
                ry0 = height - y1  # Bottom of the bbox
                ry1 = height - y0  # Top of the bbox
                
                # Calculate horizontal center
                cx = rx0 + (rx1 - rx0) / 2
                cy = ry1 + 2  # Place mark 2 points above the text box top
                
                # QuadPoints order: top-left, top-right, bottom-left, bottom-right
                quads = [rx0, ry1, rx1, ry1, rx0, ry0, rx1, ry0]
                
                if is_matched and result:
                    id_str = matched_ids.get(orig_item["label"], "")
                    if id_str:
                        # Draw green reference ID text centered above the number
                        can.setFont("Helvetica-Bold", 8)
                        can.setFillColorRGB(0.0, 0.6, 0.0)  # Green
                        text_width = can.stringWidth(id_str, "Helvetica-Bold", 8)
                        can.drawString(cx - text_width / 2, cy, id_str)
                        
                        # Tooltip text
                        annot_text = (
                            f"[{id_str}] Approved by AI\n"
                            f"Source: {result['matched_source_label']}\n"
                            f"Value: {result['matched_source_value']} {result['matched_source_unit']} (Page {result['matched_source_page']})\n"
                            f"Reason: {result['ai_reasoning']}"
                        )
                        
                        # Highlight the number in light semi-transparent green
                        annot = HighlightAnnotation(
                            Rect=[rx0, ry0, rx1, ry1],
                            Contents=annot_text,
                            QuadPoints=quads,
                            Color=[0.82, 0.94, 0.82]
                        )
                        can._addAnnotation(annot, name=None, addtopage=1)
                else:
                    # Draw warning triangle (⚠️)
                    draw_warning_mark(can, cx, cy)
                    
                    reason = result["ai_reasoning"] if result else "No matching guideline found in File B."
                    annot_text = (
                        f"Unmatched Item\n"
                        f"Label: {orig_item['label']}\n"
                        f"Value: {orig_item['value']} {orig_item['unit']}\n"
                        f"AI Reasoning: {reason}"
                    )
                    
                    # Highlight the unmatched number in light semi-transparent red/pink
                    annot = HighlightAnnotation(
                        Rect=[rx0, ry0, rx1, ry1],
                        Contents=annot_text,
                        QuadPoints=quads,
                        Color=[1.0, 0.85, 0.85]
                    )
                    can._addAnnotation(annot, name=None, addtopage=1)
            
            can.save()
            packet.seek(0)
            overlay_reader = PdfReader(packet)
            overlay_page = overlay_reader.pages[0]
            page.merge_page(overlay_page)
            
        writer.add_page(page)

    with open(output_pdf_path, "wb") as f_out:
        writer.write(f_out)
    print(f"Saved annotated File A PDF to {output_pdf_path}")


def annotate_pdf_file_b(
    pdf_path: Path,
    items_b: list[dict],
    matched_data: dict,
    matched_ids: dict[str, str],
    output_pdf_path: Path
) -> None:
    reader = PdfReader(pdf_path)
    writer = PdfWriter()

    # Group matched results by File B reference: (label, value, page)
    matched_lookup: dict[tuple[str, float, int], list[dict]] = {}
    for result in matched_data["results"]:
        if not result["matched"]:
            continue
        key = (
            result["matched_source_label"],
            float(result["matched_source_value"]),
            int(result["matched_source_page"])
        )
        if key not in matched_lookup:
            matched_lookup[key] = []
        matched_lookup[key].append(result)

    # Map page number to list of items to draw
    page_modifications: dict[int, list[tuple[dict, list[dict]]]] = {}
    
    for item in items_b:
        label = item["label"]
        value = item["value"]
        page_num = item["page"]
        
        key = (label, float(value), int(page_num))
        matches = matched_lookup.get(key)
        
        if matches:
            if page_num not in page_modifications:
                page_modifications[page_num] = []
            page_modifications[page_num].append((item, matches))

    # Process each page
    for i in range(len(reader.pages)):
        page_num = i + 1
        page = reader.pages[i]
        
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        
        if page_num in page_modifications:
            print(f"Drawing annotations on File B Page {page_num}...")
            packet = io.BytesIO()
            can = canvas.Canvas(packet, pagesize=(width, height))
            
            for item, matches in page_modifications[page_num]:
                bbox = item.get("bbox")
                if not bbox:
                    print(f"⚠️ Skipping annotation for File B matched reference '{item['label']}' (Bbox was not found)")
                    continue
                    
                x0, y0, x1, y1 = bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"]
                
                # Coordinate translation
                rx0 = x0
                rx1 = x1
                ry0 = height - y1
                ry1 = height - y0
                
                cx = rx0 + (rx1 - rx0) / 2
                cy = ry1 + 2
                
                # Collect matching reference IDs and sort them
                ids = [matched_ids[m["check_item_label"]] for m in matches if m["check_item_label"] in matched_ids]
                if not ids:
                    continue
                id_str = ", ".join(sorted(ids))
                
                # Draw blue reference ID text centered above the number
                can.setFont("Helvetica-Bold", 8)
                can.setFillColorRGB(0.0, 0.4, 0.8)  # Blue
                text_width = can.stringWidth(id_str, "Helvetica-Bold", 8)
                can.drawString(cx - text_width / 2, cy, id_str)
                
                # Construct annotation text listing all matched File A items
                lines = [f"[{id_str}] Referenced by {len(matches)} item(s) in File A:"]
                for idx, m in enumerate(matches, 1):
                    ref_id = matched_ids.get(m['check_item_label'], "??")
                    lines.append(
                        f"{idx}. [{ref_id}] Label: {m['check_item_label']}\n"
                        f"   Value: {m['check_item_value']} {m['check_item_unit']} (Page {m['check_item_page']})"
                    )
                annot_text = "\n".join(lines)
                
                # QuadPoints order: top-left, top-right, bottom-left, bottom-right
                quads = [rx0, ry1, rx1, ry1, rx0, ry0, rx1, ry0]
                
                # Highlight the reference number in light semi-transparent blue
                annot = HighlightAnnotation(
                    Rect=[rx0, ry0, rx1, ry1],
                    Contents=annot_text,
                    QuadPoints=quads,
                    Color=[0.82, 0.88, 1.0]
                )
                can._addAnnotation(annot, name=None, addtopage=1)
                
            can.save()
            packet.seek(0)
            overlay_reader = PdfReader(packet)
            overlay_page = overlay_reader.pages[0]
            page.merge_page(overlay_page)
            
        writer.add_page(page)

    with open(output_pdf_path, "wb") as f_out:
        writer.write(f_out)
    print(f"Saved annotated File B PDF to {output_pdf_path}")


def main() -> None:
    workspace_dir = Path(__file__).resolve().parents[2]
    poc_data_dir = workspace_dir / "poc" / "poc_data"
    bench_dir = workspace_dir / "bench"
    
    # Load structured File A with bboxes
    structured_a_path = poc_data_dir / "poc2_structured_a_with_bboxes.json"
    if not structured_a_path.exists():
        raise FileNotFoundError(f"Structured A file not found: {structured_a_path}")
    with open(structured_a_path, "r", encoding="utf-8") as f:
        data_a = json.load(f)
    items_a = {item["label"]: item for item in data_a["items"]}

    # Load structured File B with bboxes
    structured_b_path = poc_data_dir / "poc2_structured_b_with_bboxes.json"
    if not structured_b_path.exists():
        raise FileNotFoundError(f"Structured B file not found: {structured_b_path}")
    with open(structured_b_path, "r", encoding="utf-8") as f:
        data_b = json.load(f)
    items_b = data_b["items"]

    # Load PoC-1 matched results
    matched_results_path = poc_data_dir / "poc1_matched_results.json"
    if not matched_results_path.exists():
        raise FileNotFoundError(f"Matched results file not found: {matched_results_path}")
    with open(matched_results_path, "r", encoding="utf-8") as f:
        matched_data = json.load(f)

    # Generate sequential cross-reference IDs for matched items
    matched_ids: dict[str, str] = {}
    matched_idx = 1
    for result in matched_data["results"]:
        if result["matched"]:
            label = result["check_item_label"]
            matched_ids[label] = f"c{matched_idx:02d}"
            matched_idx += 1

    # Annotate File A
    file_a_pdf = bench_dir / "sample_file_a_keisan.pdf"
    file_a_out = poc_data_dir / "poc2_annotated_file_a.pdf"
    annotate_pdf_file_a(file_a_pdf, items_a, matched_data, matched_ids, file_a_out)

    # Annotate File B
    file_b_pdf = bench_dir / "sample_file_b_kajushishin.pdf"
    file_b_out = poc_data_dir / "poc2_annotated_file_b.pdf"
    annotate_pdf_file_b(file_b_pdf, items_b, matched_data, matched_ids, file_b_out)

if __name__ == "__main__":
    main()
