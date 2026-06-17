from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import cast
import uuid
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import zipfile
from pydantic import BaseModel

from app.db.database import get_db
from app.db.models import (
    SourceDocument,
    SourceItem,
    CheckSession,
    CheckItem,
    MatchResult,
)
from app.services.extractor import extract_source_items_from_pdf
from app.services.annotator import (
    annotate_pdf_file_b,
    annotate_pdf_file_a,
    annotate_pdf_file_b_extracted,
)

router = APIRouter(prefix="/api/v1/source-documents", tags=["source-documents"])


class SourceDocumentResponse(BaseModel):
    id: str
    filename: str
    title: str | None
    version: str | None
    uploaded_at: datetime
    item_count: int
    categories: list[str] | None = None

    class Config:
        from_attributes = True


class SourceItemResponse(BaseModel):
    id: str
    document_id: str
    page: int
    label: str
    value_type: str = "numeric"
    value: float | None = None
    text_value: str | None = None
    formula_value: str | None = None
    unit: str | None = None
    context_text: str
    bbox: dict | None = None
    category: str | None = None
    source_block_ids: list[str] | None = None

    class Config:
        from_attributes = True


@router.post(
    "", response_model=SourceDocumentResponse, status_code=status.HTTP_201_CREATED
)
async def upload_source_document(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    version: str | None = Form(None),
    categories: str | None = Form(None),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Filename is missing"
        )

    # Read file content and calculate hash
    try:
        content = file.file.read()
        file_hash = hashlib.sha256(content).hexdigest()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read file: {e}",
        )

    # Check for duplicate document
    existing_doc = (
        db.query(SourceDocument).filter(SourceDocument.file_hash == file_hash).first()
    )
    if existing_doc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"このファイルは既に登録されています。 (ID: {existing_doc.id}, タイトル: {existing_doc.title})",
        )

    # Ensure uploads folder exists in project root directory
    base_dir = Path(__file__).resolve().parents[3]
    uploads_dir = base_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # Save the file
    doc_id = str(uuid.uuid4())
    file_extension = Path(file.filename).suffix
    saved_filename = f"{doc_id}{file_extension}"
    saved_path = uploads_dir / saved_filename

    try:
        with open(saved_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save file: {e}",
        )

    # Extract items
    cats_list = None
    if categories:
        cats_list = [c.strip() for c in categories.split(",") if c.strip()]

    try:
        extracted_items = await extract_source_items_from_pdf(
            saved_path, categories=cats_list
        )
    except Exception as e:
        # Clean up file on failure
        if saved_path.exists():
            saved_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to extract text and data from PDF: {e}",
        )

    # Save document
    doc = SourceDocument(
        id=doc_id,
        filename=file.filename,
        title=title or file.filename,
        version=version,
        uploaded_at=datetime.now(timezone.utc),
        file_hash=file_hash,
        categories=cats_list,
    )
    db.add(doc)

    # Save items
    for item in extracted_items:
        source_item = SourceItem(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            page=int(item["page"]),
            label=str(item["label"]),
            value_type=str(item.get("value_type", "numeric")),
            value=float(item["value"]) if item.get("value") is not None else None,
            text_value=item.get("text_value"),
            formula_value=item.get("formula_value"),
            unit=str(item["unit"]) if item.get("unit") else None,
            context_text=str(item["context_text"]),
            bbox=item.get("bbox"),
            category=item.get("category"),
            source_block_ids=item.get("source_block_ids"),
        )
        db.add(source_item)

    db.commit()
    db.refresh(doc)

    return SourceDocumentResponse(
        id=str(doc.id),
        filename=str(doc.filename),
        title=str(doc.title) if doc.title else None,
        version=str(doc.version) if doc.version else None,
        uploaded_at=datetime.now(timezone.utc),  # use timezone-aware datetime
        item_count=len(extracted_items),
        categories=cast(list[str] | None, doc.categories),
    )


@router.get("", response_model=list[SourceDocumentResponse])
def list_source_documents(db: Session = Depends(get_db)):
    docs = db.query(SourceDocument).all()
    results = []
    for doc in docs:
        item_count = (
            db.query(SourceItem).filter(SourceItem.document_id == doc.id).count()
        )
        results.append(
            SourceDocumentResponse(
                id=str(doc.id),
                filename=str(doc.filename),
                title=str(doc.title) if doc.title else None,
                version=str(doc.version) if doc.version else None,
                uploaded_at=cast(datetime, doc.uploaded_at),
                item_count=item_count,
                categories=cast(list[str] | None, doc.categories),
            )
        )
    return results


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.query(SourceDocument).filter(SourceDocument.id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source document with id {document_id} not found",
        )

    db.delete(doc)
    db.commit()
    return None


@router.get("/{document_id}/items", response_model=list[SourceItemResponse])
def get_source_document_items(document_id: str, db: Session = Depends(get_db)):
    doc = db.query(SourceDocument).filter(SourceDocument.id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source document with id {document_id} not found",
        )
    items = db.query(SourceItem).filter(SourceItem.document_id == document_id).all()
    results = []
    for item in items:
        results.append(
            SourceItemResponse(
                id=str(item.id),
                document_id=str(item.document_id),
                page=cast(int, item.page),
                label=str(item.label),
                value_type=str(item.value_type) if item.value_type else "numeric",
                value=cast(float | None, item.value),
                text_value=str(item.text_value) if item.text_value else None,
                formula_value=str(item.formula_value) if item.formula_value else None,
                unit=str(item.unit) if item.unit else None,
                context_text=str(item.context_text),
                bbox=cast(dict | None, item.bbox),
                category=str(item.category) if item.category else None,
                source_block_ids=cast(list[str] | None, item.source_block_ids),
            )
        )
    return results


@router.post("/sessions/{session_id}/export-all")
def export_all_source_annotated_pdfs(session_id: str, db: Session = Depends(get_db)):
    session = db.query(CheckSession).filter(CheckSession.id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with id {session_id} not found",
        )

    check_items = db.query(CheckItem).filter(CheckItem.session_id == session_id).all()
    if not check_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No check items in this session",
        )

    check_item_ids = [item.id for item in check_items]
    match_results = (
        db.query(MatchResult)
        .filter(MatchResult.check_item_id.in_(check_item_ids))
        .all()
    )

    # Generate mapping IDs to match File A's output
    matched_ids = {}
    matched_idx = 1
    for r in match_results:
        if r.status == "approved":
            matched_ids[r.check_item_id] = f"c{matched_idx:02d}"
            matched_idx += 1

    # Find all SourceDocuments that have approved matches in this session
    source_doc_ids = set()
    for r in match_results:
        if r.status == "approved" and r.source_item_id:
            s_item = (
                db.query(SourceItem).filter(SourceItem.id == r.source_item_id).first()
            )
            if s_item:
                source_doc_ids.add(s_item.document_id)

    if not source_doc_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="このセッションで承認された(AIまたは手動でApprovedになった)出典データが見つかりません。そのため出典注釈PDFをエクスポートできません。",
        )

    base_dir = Path(__file__).resolve().parents[3]
    uploads_dir = base_dir / "uploads"

    zip_filename = f"{session_id}_sources_annotated.zip"
    zip_path = uploads_dir / zip_filename

    try:
        with zipfile.ZipFile(zip_path, "w") as zipf:
            # 1. Generate annotated PDF for File A (Calculation Sheet) and write to ZIP
            pdf_path_a = Path(str(session.file_a_path))
            if pdf_path_a.exists():
                items_a = []
                for item in check_items:
                    items_a.append(
                        {
                            "id": str(item.id),
                            "label": str(item.label),
                            "value": cast(float, item.value),
                            "unit": str(item.unit),
                            "page": cast(int, item.page),
                            "bbox": cast(dict | None, item.bbox),
                            "context": str(item.context),
                        }
                    )

                results_a = []
                for r in match_results:
                    check_item = next(
                        (ci for ci in check_items if ci.id == r.check_item_id), None
                    )
                    if not check_item:
                        continue

                    s_label = ""
                    s_value = 0.0
                    s_unit = ""
                    s_page = 0

                    if r.source_item_id:
                        s_item = (
                            db.query(SourceItem)
                            .filter(SourceItem.id == r.source_item_id)
                            .first()
                        )
                        if s_item:
                            s_label = str(s_item.label)
                            s_value = cast(float, s_item.value)
                            s_unit = str(s_item.unit)
                            s_page = cast(int, s_item.page)

                    results_a.append(
                        {
                            "check_item_id": str(r.check_item_id),
                            "matched": r.status == "approved",
                            "confidence": cast(float, r.confidence),
                            "ai_reasoning": str(r.ai_reasoning),
                            "matched_source_label": s_label,
                            "matched_source_value": s_value,
                            "matched_source_unit": s_unit,
                            "matched_source_page": s_page,
                        }
                    )

                import re

                raw_filename_a = pdf_path_a.name
                clean_filename_a = re.sub(
                    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_?",
                    "",
                    raw_filename_a,
                )
                if not clean_filename_a.endswith(".pdf"):
                    clean_filename_a += ".pdf"

                temp_output_path_a = (
                    uploads_dir / f"{session_id}_file_a_temp_annotated.pdf"
                )
                annotate_pdf_file_a(pdf_path_a, items_a, results_a, temp_output_path_a)

                zipf.write(temp_output_path_a, arcname=f"annotated_{clean_filename_a}")
                if temp_output_path_a.exists():
                    temp_output_path_a.unlink()

            # 2. Generate annotated PDFs for File B (Source Documents) and write to ZIP
            for doc_id in source_doc_ids:
                doc = (
                    db.query(SourceDocument).filter(SourceDocument.id == doc_id).first()
                )
                if not doc:
                    continue

                # Fetch items for this document
                source_items = (
                    db.query(SourceItem).filter(SourceItem.document_id == doc_id).all()
                )
                source_items_data = []
                for item in source_items:
                    source_items_data.append(
                        {
                            "id": str(item.id),
                            "label": str(item.label),
                            "value": float(cast(float, item.value))
                            if item.value is not None
                            else 0.0,
                            "unit": str(item.unit),
                            "page": int(cast(int, item.page)),
                            "bbox": item.bbox,
                            "context_text": str(item.context_text),
                        }
                    )

                # Collect match results for this document
                annot_results = []
                for r in match_results:
                    if r.source_item_id and r.status == "approved":
                        s_item = next(
                            (si for si in source_items if si.id == r.source_item_id),
                            None,
                        )
                        if s_item:
                            check_item = next(
                                (ci for ci in check_items if ci.id == r.check_item_id),
                                None,
                            )
                            if check_item:
                                annot_results.append(
                                    {
                                        "source_item_id": str(r.source_item_id),
                                        "mapping_id": matched_ids.get(r.check_item_id),
                                        "check_item_label": str(check_item.label),
                                        "check_item_value": float(
                                            cast(float, check_item.value)
                                        )
                                        if check_item.value is not None
                                        else 0.0,
                                        "check_item_unit": str(check_item.unit),
                                        "check_item_page": int(
                                            cast(int, check_item.page)
                                        ),
                                        "ai_reasoning": str(r.ai_reasoning),
                                    }
                                )

                file_extension = Path(cast(str, doc.filename)).suffix or ".pdf"
                orig_pdf_path = uploads_dir / f"{doc_id}{file_extension}"
                if not orig_pdf_path.exists():
                    continue

                temp_output_path = (
                    uploads_dir / f"{session_id}_{doc_id}_temp_annotated.pdf"
                )

                # Annotate PDF
                annotate_pdf_file_b(
                    orig_pdf_path, source_items_data, annot_results, temp_output_path
                )

                # Write to zip
                arcname = f"annotated_{doc.title or doc.filename}"
                if not arcname.endswith(".pdf"):
                    arcname += ".pdf"
                zipf.write(temp_output_path, arcname=arcname)

                # Delete temp file
                if temp_output_path.exists():
                    temp_output_path.unlink()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ZIP一括エクスポートに失敗しました: {e}",
        )

    return FileResponse(
        path=zip_path, media_type="application/zip", filename="annotated_sources.zip"
    )


@router.post("/sessions/{session_id}/source-documents/{document_id}/export")
def export_single_source_annotated_pdf(
    session_id: str, document_id: str, db: Session = Depends(get_db)
):
    session = db.query(CheckSession).filter(CheckSession.id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with id {session_id} not found",
        )

    doc = db.query(SourceDocument).filter(SourceDocument.id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source document with id {document_id} not found",
        )

    check_items = db.query(CheckItem).filter(CheckItem.session_id == session_id).all()
    check_item_ids = [item.id for item in check_items]
    match_results = (
        db.query(MatchResult)
        .filter(MatchResult.check_item_id.in_(check_item_ids))
        .all()
    )

    # Generate mapping IDs to match File A's output
    matched_ids = {}
    matched_idx = 1
    for r in match_results:
        if r.status == "approved":
            matched_ids[r.check_item_id] = f"c{matched_idx:02d}"
            matched_idx += 1

    # Fetch source items
    source_items = (
        db.query(SourceItem).filter(SourceItem.document_id == document_id).all()
    )
    source_items_data = []
    for item in source_items:
        source_items_data.append(
            {
                "id": str(item.id),
                "label": str(item.label),
                "value": float(cast(float, item.value))
                if item.value is not None
                else 0.0,
                "unit": str(item.unit),
                "page": int(cast(int, item.page)),
                "bbox": item.bbox,
                "context_text": str(item.context_text),
            }
        )

    # Collect match results for this document
    annot_results = []
    for r in match_results:
        if r.source_item_id and r.status == "approved":
            s_item = next(
                (si for si in source_items if si.id == r.source_item_id), None
            )
            if s_item:
                check_item = next(
                    (ci for ci in check_items if ci.id == r.check_item_id), None
                )
                if check_item:
                    annot_results.append(
                        {
                            "source_item_id": str(r.source_item_id),
                            "mapping_id": matched_ids.get(r.check_item_id),
                            "check_item_label": str(check_item.label),
                            "check_item_value": float(cast(float, check_item.value))
                            if check_item.value is not None
                            else 0.0,
                            "check_item_unit": str(check_item.unit),
                            "check_item_page": int(cast(int, check_item.page)),
                            "ai_reasoning": str(r.ai_reasoning),
                        }
                    )

    base_dir = Path(__file__).resolve().parents[3]
    uploads_dir = base_dir / "uploads"

    file_extension = Path(cast(str, doc.filename)).suffix or ".pdf"
    orig_pdf_path = uploads_dir / f"{document_id}{file_extension}"
    if not orig_pdf_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Original PDF file not found at: {orig_pdf_path}",
        )

    output_filename = f"{session_id}_{document_id}_annotated.pdf"
    output_path = uploads_dir / output_filename

    try:
        annotate_pdf_file_b(
            orig_pdf_path, source_items_data, annot_results, output_path
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to annotate Source PDF: {e}",
        )

    download_filename = f"annotated_{doc.title or doc.filename}"
    if not download_filename.endswith(".pdf"):
        download_filename += ".pdf"

    return FileResponse(
        path=output_path, media_type="application/pdf", filename=download_filename
    )


@router.get("/{document_id}/export-extracted")
def export_extracted_source_pdf(document_id: str, db: Session = Depends(get_db)):
    doc = db.query(SourceDocument).filter(SourceDocument.id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source document with id {document_id} not found",
        )

    source_items = (
        db.query(SourceItem).filter(SourceItem.document_id == document_id).all()
    )
    source_items_data = []
    for item in source_items:
        source_items_data.append(
            {
                "id": str(item.id),
                "label": str(item.label),
                "value": float(cast(float, item.value))
                if item.value is not None
                else 0.0,
                "unit": str(item.unit),
                "page": int(cast(int, item.page)),
                "bbox": item.bbox,
                "context_text": str(item.context_text),
            }
        )

    base_dir = Path(__file__).resolve().parents[3]
    uploads_dir = base_dir / "uploads"

    file_extension = Path(cast(str, doc.filename)).suffix or ".pdf"
    orig_pdf_path = uploads_dir / f"{document_id}{file_extension}"
    if not orig_pdf_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Original PDF file not found at: {orig_pdf_path}",
        )

    output_filename = f"extracted_{document_id}.pdf"
    output_path = uploads_dir / output_filename

    try:
        annotate_pdf_file_b_extracted(orig_pdf_path, source_items_data, output_path)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to annotate Source PDF: {e}",
        )

    download_filename = f"extracted_{doc.title or doc.filename}"
    if not download_filename.endswith(".pdf"):
        download_filename += ".pdf"

    return FileResponse(
        path=output_path, media_type="application/pdf", filename=download_filename
    )
