import io
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfdoc import HighlightAnnotation

def draw_warning_mark(can: canvas.Canvas, cx: float, cy: float) -> None:
    # Draw warning triangle (⚠️) in orange/yellow
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
    items_a: list[dict],
    results: list[dict],
    output_pdf_path: Path
) -> None:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    reader = PdfReader(pdf_path)
    writer = PdfWriter()

    results_lookup = {r["check_item_id"]: r for r in results}

    matched_ids: dict[str, str] = {}
    matched_idx = 1
    for r in results:
        if r["matched"]:
            matched_ids[r["check_item_id"]] = f"c{matched_idx:02d}"
            matched_idx += 1

    page_modifications: dict[int, list[tuple[dict, dict | None]]] = {}
    for item in items_a:
        page_num = int(item["page"])
        if page_num not in page_modifications:
            page_modifications[page_num] = []
        result = results_lookup.get(item["id"])
        page_modifications[page_num].append((item, result))

    for i in range(len(reader.pages)):
        page_num = i + 1
        page = reader.pages[i]
        
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        
        if page_num in page_modifications:
            packet = io.BytesIO()
            can = canvas.Canvas(packet, pagesize=(width, height))
            
            for item, result in page_modifications[page_num]:
                bbox = item.get("bbox")
                if not bbox:
                    continue
                    
                x0 = float(bbox["x0"])
                y0 = float(bbox["y0"])
                x1 = float(bbox["x1"])
                y1 = float(bbox["y1"])
                
                rx0 = x0
                rx1 = x1
                ry0 = height - y1
                ry1 = height - y0
                
                cx = rx0 + (rx1 - rx0) / 2
                cy = ry1 + 2
                
                quads = [rx0, ry1, rx1, ry1, rx0, ry0, rx1, ry0]
                
                is_matched = result["matched"] if result else False
                
                if is_matched and result:
                    id_str = matched_ids.get(item["id"], "")
                    if id_str:
                        can.setFont("Helvetica-Bold", 8)
                        can.setFillColorRGB(0.0, 0.6, 0.0)
                        text_width = can.stringWidth(id_str, "Helvetica-Bold", 8)
                        can.drawString(cx - text_width / 2, cy, id_str)
                        
                        annot_text = (
                            f"[{id_str}] Approved by AI\n"
                            f"Source: {result.get('matched_source_label')}\n"
                            f"Value: {result.get('matched_source_value')} {result.get('matched_source_unit')} (Page {result.get('matched_source_page')})\n"
                            f"Reason: {result.get('ai_reasoning')}"
                        )
                        
                        annot = HighlightAnnotation(
                            Rect=[rx0, ry0, rx1, ry1],
                            Contents=annot_text,
                            QuadPoints=quads,
                            Color=[0.82, 0.94, 0.82]
                        )
                        can._addAnnotation(annot, name=None, addtopage=1)
                else:
                    draw_warning_mark(can, cx, cy)
                    
                    reason = result.get("ai_reasoning") if result else "No matching guideline found in reference documents."
                    annot_text = (
                        f"Unmatched Item\n"
                        f"Label: {item['label']}\n"
                        f"Value: {item['value']} {item['unit']}\n"
                        f"AI Reasoning: {reason}"
                    )
                    
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
            if len(overlay_reader.pages) > 0:
                overlay_page = overlay_reader.pages[0]
                page.merge_page(overlay_page)
            
        writer.add_page(page)

    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_pdf_path, "wb") as f_out:
        writer.write(f_out)
