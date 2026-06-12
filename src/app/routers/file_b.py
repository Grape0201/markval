from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from sqlalchemy.orm import Session
from typing import cast
import uuid
from datetime import datetime, timezone
from pathlib import Path
import hashlib
from pydantic import BaseModel

from app.db.database import get_db
from app.db.models import SourceDocument, SourceItem
from app.services.extractor import extract_source_items_from_pdf

router = APIRouter(prefix="/api/v1/source-documents", tags=["source-documents"])

class SourceDocumentResponse(BaseModel):
    id: str
    filename: str
    title: str | None
    version: str | None
    uploaded_at: datetime
    item_count: int

    class Config:
        from_attributes = True


class SourceItemResponse(BaseModel):
    id: str
    document_id: str
    page: int
    label: str
    value: float
    unit: str
    context_text: str
    bbox: dict | None = None
    category: str | None = None

    class Config:
        from_attributes = True


@router.post("", response_model=SourceDocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_source_document(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    version: str | None = Form(None),
    categories: str | None = Form(None),
    db: Session = Depends(get_db)
):
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is missing"
        )
    
    # Read file content and calculate hash
    try:
        content = file.file.read()
        file_hash = hashlib.sha256(content).hexdigest()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read file: {e}"
        )

    # Check for duplicate document
    existing_doc = db.query(SourceDocument).filter(SourceDocument.file_hash == file_hash).first()
    if existing_doc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"このファイルは既に登録されています。 (ID: {existing_doc.id}, タイトル: {existing_doc.title})"
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
            detail=f"Failed to save file: {e}"
        )
        
    # Extract items
    cats_list = None
    if categories:
        cats_list = [c.strip() for c in categories.split(",") if c.strip()]
        
    try:
        extracted_items = await extract_source_items_from_pdf(saved_path, categories=cats_list)
    except Exception as e:
        # Clean up file on failure
        if saved_path.exists():
            saved_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to extract text and data from PDF: {e}"
        )

    # Save document
    doc = SourceDocument(
        id=doc_id,
        filename=file.filename,
        title=title or file.filename,
        version=version,
        uploaded_at=datetime.now(timezone.utc),
        file_hash=file_hash
    )
    db.add(doc)
    
    # Save items
    for item in extracted_items:
        source_item = SourceItem(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            page=int(item["page"]),
            label=str(item["label"]),
            value=float(item["value"]),
            unit=str(item["unit"]),
            context_text=str(item["context_text"]),
            bbox=item.get("bbox"),
            category=item.get("category")
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
        item_count=len(extracted_items)
    )


@router.get("", response_model=list[SourceDocumentResponse])
def list_source_documents(db: Session = Depends(get_db)):
    docs = db.query(SourceDocument).all()
    results = []
    for doc in docs:
        item_count = db.query(SourceItem).filter(SourceItem.document_id == doc.id).count()
        results.append(SourceDocumentResponse(
            id=str(doc.id),
            filename=str(doc.filename),
            title=str(doc.title) if doc.title else None,
            version=str(doc.version) if doc.version else None,
            uploaded_at=cast(datetime, doc.uploaded_at),
            item_count=item_count
        ))
    return results


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.query(SourceDocument).filter(SourceDocument.id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source document with id {document_id} not found"
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
            detail=f"Source document with id {document_id} not found"
        )
    items = db.query(SourceItem).filter(SourceItem.document_id == document_id).all()
    results = []
    for item in items:
        results.append(SourceItemResponse(
            id=str(item.id),
            document_id=str(item.document_id),
            page=cast(int, item.page),
            label=str(item.label),
            value=cast(float, item.value),
            unit=str(item.unit),
            context_text=str(item.context_text),
            bbox=cast(dict | None, item.bbox),
            category=str(item.category) if item.category else None
        ))
    return results
