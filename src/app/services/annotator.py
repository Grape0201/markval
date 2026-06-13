import io
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfdoc import HighlightAnnotation


def draw_warning_mark(can: canvas.Canvas, cx: float, cy: float) -> None:
    # Draw warning triangle (⚠️) in orange/yellow
    can.setStrokeColorRGB(0.8, 0.4, 0.0)  # Dark orange outline
    can.setFillColorRGB(1.0, 0.75, 0.0)  # Yellow/orange fill
    can.setLineWidth(1.0)
    p = can.beginPath()
    p.moveTo(cx, cy + 8)  # Top
    p.lineTo(cx - 5, cy)  # Bottom left
    p.lineTo(cx + 5, cy)  # Bottom right
    p.close()
    can.drawPath(p, stroke=True, fill=True)

    # Exclamation point (!) inside the triangle
    can.setStrokeColorRGB(0.0, 0.0, 0.0)
    can.setLineWidth(1.0)
    can.line(cx, cy + 5.5, cx, cy + 2.5)  # Vertical bar

    can.setFillColorRGB(0.0, 0.0, 0.0)
    can.rect(cx - 0.5, cy + 0.8, 1.0, 1.0, stroke=0, fill=1)  # Dot


def annotate_pdf_file_a(
    pdf_path: Path, items_a: list[dict], results: list[dict], output_pdf_path: Path
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
                            Color=[0.82, 0.94, 0.82],
                        )
                        can._addAnnotation(annot, name=None, addtopage=1)
                else:
                    draw_warning_mark(can, cx, cy)

                    reason = (
                        result.get("ai_reasoning")
                        if result
                        else "No matching guideline found in reference documents."
                    )
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
                        Color=[1.0, 0.85, 0.85],
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


def annotate_pdf_file_b(
    pdf_path: Path, source_items: list[dict], results: list[dict], output_pdf_path: Path
) -> None:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    reader = PdfReader(pdf_path)
    writer = PdfWriter()

    # Create a lookup for results based on source_item_id
    results_lookup: dict[str, list[dict]] = {}
    for r in results:
        s_id = r.get("source_item_id")
        if s_id:
            if s_id not in results_lookup:
                results_lookup[s_id] = []
            results_lookup[s_id].append(r)

    page_modifications: dict[int, list[tuple[dict, list[dict]]]] = {}
    for item in source_items:
        page_num = int(item["page"])
        if page_num not in page_modifications:
            page_modifications[page_num] = []

        # Only modify if this item has approved match results
        item_results = results_lookup.get(item["id"], [])
        approved_results = [r for r in item_results if r.get("mapping_id")]
        if approved_results:
            page_modifications[page_num].append((item, approved_results))

    for i in range(len(reader.pages)):
        page_num = i + 1
        page = reader.pages[i]

        width = float(page.mediabox.width)
        height = float(page.mediabox.height)

        if page_num in page_modifications:
            packet = io.BytesIO()
            can = canvas.Canvas(packet, pagesize=(width, height))

            for item, app_results in page_modifications[page_num]:
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

                # Draw the mapping ID text. If multiple CheckItems matched, list them (e.g. "c01, c02")
                ids_str = ", ".join([r["mapping_id"] for r in app_results])

                can.setFont("Helvetica-Bold", 8)
                can.setFillColorRGB(0.0, 0.5, 0.7)  # Blueish color for File B
                text_width = can.stringWidth(ids_str, "Helvetica-Bold", 8)
                can.drawString(cx - text_width / 2, cy, ids_str)

                # Create detailed description for popup annotation
                annot_lines = [f"[{ids_str}] Matched with Calculator"]
                for r in app_results:
                    annot_lines.append(
                        f"-------------------\n"
                        f"Calculated Item: {r.get('check_item_label')}\n"
                        f"Value: {r.get('check_item_value')} {r.get('check_item_unit')} (Page {r.get('check_item_page')})\n"
                        f"Reason: {r.get('ai_reasoning')}"
                    )
                annot_text = "\n".join(annot_lines)

                annot = HighlightAnnotation(
                    Rect=[rx0, ry0, rx1, ry1],
                    Contents=annot_text,
                    QuadPoints=quads,
                    Color=[
                        0.82,
                        0.92,
                        0.94,
                    ],  # Soft light blue highlight for source documents
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


def annotate_pdf_file_b_extracted(
    pdf_path: Path, source_items: list[dict], output_pdf_path: Path
) -> None:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    reader = PdfReader(pdf_path)
    writer = PdfWriter()

    page_modifications: dict[int, list[dict]] = {}
    for item in source_items:
        page_num = int(item["page"])
        if page_num not in page_modifications:
            page_modifications[page_num] = []
        page_modifications[page_num].append(item)

    for i in range(len(reader.pages)):
        page_num = i + 1
        page = reader.pages[i]

        width = float(page.mediabox.width)
        height = float(page.mediabox.height)

        if page_num in page_modifications:
            packet = io.BytesIO()
            can = canvas.Canvas(packet, pagesize=(width, height))

            for item in page_modifications[page_num]:
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

                label = item.get("label", "")
                val = item.get("value", 0.0)
                unit = item.get("unit", "")
                category = item.get("category", "")
                context = item.get("context_text", "")

                disp_str = f"{label}: {val}"
                if len(disp_str) > 15:
                    disp_str = disp_str[:12] + "..."

                can.setFont("Helvetica-Bold", 6)
                can.setFillColorRGB(0.6, 0.4, 0.0)
                text_width = can.stringWidth(disp_str, "Helvetica-Bold", 6)
                can.drawString(cx - text_width / 2, cy, disp_str)

                annot_text = (
                    f"Extracted Source Item\n"
                    f"Label: {label}\n"
                    f"Value: {val} {unit}\n"
                    f"Category: {category or 'None'}\n"
                    f"Context: {context}"
                )

                annot = HighlightAnnotation(
                    Rect=[rx0, ry0, rx1, ry1],
                    Contents=annot_text,
                    QuadPoints=quads,
                    Color=[1.0, 0.9, 0.6],  # Soft light orange/yellow
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
