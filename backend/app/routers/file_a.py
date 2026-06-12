from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import cast
import uuid
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel

from app.db.database import get_db
from app.db.models import CheckSession, CheckItem, MatchResult, SourceItem
from app.services.extractor import extract_check_items_from_pdf
from app.services.annotator import annotate_pdf_file_a

router = APIRouter(tags=["sessions"])

class CheckSessionResponse(BaseModel):
    id: str
    file_a_path: str
    prompt_template_id: str | None
    status: str
    created_at: datetime
    item_count: int

    class Config:
        from_attributes = True

class CheckItemResponse(BaseModel):
    id: str
    session_id: str
    label: str
    value: float
    unit: str
    bbox: dict | None
    page: int
    context: str
    source_hint: str | None
    category: str | None = None

    class Config:
        from_attributes = True

class SourceItemInfo(BaseModel):
    label: str
    value: float
    unit: str
    page: int
    context_text: str
    category: str | None = None

class MatchResultResponse(BaseModel):
    id: str
    check_item_id: str
    check_item_label: str
    check_item_value: float
    check_item_unit: str
    check_item_page: int
    matched: bool
    confidence: float
    status: str
    ai_reasoning: str
    source_item: SourceItemInfo | None

    class Config:
        from_attributes = True

class ResultStatusUpdate(BaseModel):
    status: str  # approved, rejected, pending


@router.post("/api/v1/sessions", response_model=CheckSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    file: UploadFile = File(...),
    prompt_template_id: str | None = Form(None),
    categories: str | None = Form(None),
    db: Session = Depends(get_db)
):
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is missing"
        )
        
    base_dir = Path(__file__).resolve().parent.parent.parent
    uploads_dir = base_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    
    session_id = str(uuid.uuid4())
    file_extension = Path(file.filename).suffix
    saved_filename = f"{session_id}{file_extension}"
    saved_path = uploads_dir / saved_filename
    
    try:
        with open(saved_path, "wb") as f:
            content = file.file.read()
            f.write(content)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save file: {e}"
        )
        
    cats_list = None
    if categories:
        cats_list = [c.strip() for c in categories.split(",") if c.strip()]

    try:
        extracted_items = await extract_check_items_from_pdf(saved_path, categories=cats_list)
    except Exception as e:
        if saved_path.exists():
            saved_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to extract check items from PDF: {e}"
        )
        
    session = CheckSession(
        id=session_id,
        file_a_path=str(saved_path),
        prompt_template_id=prompt_template_id,
        status="pending",
        created_at=datetime.now(timezone.utc)
    )
    db.add(session)
    
    for item in extracted_items:
        check_item = CheckItem(
            id=str(uuid.uuid4()),
            session_id=session_id,
            label=str(item["label"]),
            value=float(item["value"]),
            unit=str(item["unit"]),
            bbox=item.get("bbox"),
            page=int(item["page"]),
            context=str(item["context"]),
            source_hint=str(item["source_hint"]) if item.get("source_hint") else None,
            category=item.get("category")
        )
        db.add(check_item)
        
    db.commit()
    db.refresh(session)
    
    return CheckSessionResponse(
        id=str(session.id),
        file_a_path=str(session.file_a_path),
        prompt_template_id=str(session.prompt_template_id) if session.prompt_template_id else None,
        status=str(session.status),
        created_at=cast(datetime, session.created_at),
        item_count=len(extracted_items)
    )


@router.get("/api/v1/sessions", response_model=list[CheckSessionResponse])
def list_sessions(db: Session = Depends(get_db)):
    sessions = db.query(CheckSession).order_by(CheckSession.created_at.desc()).all()
    results = []
    for s in sessions:
        item_count = db.query(CheckItem).filter(CheckItem.session_id == s.id).count()
        results.append(CheckSessionResponse(
            id=str(s.id),
            file_a_path=str(s.file_a_path),
            prompt_template_id=str(s.prompt_template_id) if s.prompt_template_id else None,
            status=str(s.status),
            created_at=cast(datetime, s.created_at),
            item_count=item_count
        ))
    return results


@router.get("/api/v1/sessions/{session_id}/items", response_model=list[CheckItemResponse])
def get_session_items(session_id: str, db: Session = Depends(get_db)):
    session = db.query(CheckSession).filter(CheckSession.id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with id {session_id} not found"
        )
    items = db.query(CheckItem).filter(CheckItem.session_id == session_id).all()
    
    results = []
    for item in items:
        results.append(CheckItemResponse(
            id=str(item.id),
            session_id=str(item.session_id),
            label=str(item.label),
            value=cast(float, item.value),
            unit=str(item.unit),
            bbox=cast(dict | None, item.bbox),
            page=cast(int, item.page),
            context=str(item.context),
            source_hint=str(item.source_hint) if item.source_hint else None,
            category=str(item.category) if item.category else None
        ))
    return results


@router.get("/api/v1/sessions/{session_id}/results", response_model=list[MatchResultResponse])
def get_session_results(session_id: str, db: Session = Depends(get_db)):
    session = db.query(CheckSession).filter(CheckSession.id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with id {session_id} not found"
        )
    
    check_items = db.query(CheckItem).filter(CheckItem.session_id == session_id).all()
    check_item_ids = [item.id for item in check_items]
    
    match_results = db.query(MatchResult).filter(MatchResult.check_item_id.in_(check_item_ids)).all()
    
    response_list = []
    for result in match_results:
        check_item = db.query(CheckItem).filter(CheckItem.id == result.check_item_id).first()
        if not check_item:
            continue
            
        source_item = None
        if result.source_item_id:
            s_item = db.query(SourceItem).filter(SourceItem.id == result.source_item_id).first()
            if s_item:
                source_item = SourceItemInfo(
                    label=str(s_item.label),
                    value=cast(float, s_item.value),
                    unit=str(s_item.unit),
                    page=cast(int, s_item.page),
                    context_text=str(s_item.context_text),
                    category=str(s_item.category) if s_item.category else None
                )
                
        response_list.append(MatchResultResponse(
            id=str(result.id),
            check_item_id=str(result.check_item_id),
            check_item_label=str(check_item.label),
            check_item_value=cast(float, check_item.value),
            check_item_unit=str(check_item.unit),
            check_item_page=cast(int, check_item.page),
            matched=bool(result.status == "approved"),
            confidence=cast(float, result.confidence),
            status=str(result.status),
            ai_reasoning=str(result.ai_reasoning),
            source_item=source_item
        ))
    return response_list


@router.patch("/api/v1/results/{result_id}", response_model=MatchResultResponse)
def update_result_status(result_id: str, payload: ResultStatusUpdate, db: Session = Depends(get_db)):
    result = db.query(MatchResult).filter(MatchResult.id == result_id).first()
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Match result with id {result_id} not found"
        )
        
    if payload.status not in ["approved", "rejected", "pending"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid status value. Must be 'approved', 'rejected', or 'pending'."
        )
        
    setattr(result, "status", payload.status)
    db.commit()
    db.refresh(result)
    
    check_item = db.query(CheckItem).filter(CheckItem.id == result.check_item_id).first()
    if not check_item:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Check item associated with this match result not found"
        )
        
    source_item = None
    if result.source_item_id:
        s_item = db.query(SourceItem).filter(SourceItem.id == result.source_item_id).first()
        if s_item:
            source_item = SourceItemInfo(
                label=str(s_item.label),
                value=cast(float, s_item.value),
                unit=str(s_item.unit),
                page=cast(int, s_item.page),
                context_text=str(s_item.context_text),
                category=str(s_item.category) if s_item.category else None
            )
            
    return MatchResultResponse(
        id=str(result.id),
        check_item_id=str(result.check_item_id),
        check_item_label=str(check_item.label),
        check_item_value=cast(float, check_item.value),
        check_item_unit=str(check_item.unit),
        check_item_page=cast(int, check_item.page),
        matched=bool(result.status == "approved"),
        confidence=cast(float, result.confidence),
        status=str(result.status),
        ai_reasoning=str(result.ai_reasoning),
        source_item=source_item
    )


@router.post("/api/v1/sessions/{session_id}/export")
def export_annotated_pdf(session_id: str, db: Session = Depends(get_db)):
    session = db.query(CheckSession).filter(CheckSession.id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with id {session_id} not found"
        )
        
    pdf_path = Path(str(session.file_a_path))
    if not pdf_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Original PDF file not found at: {pdf_path}"
        )
        
    check_items = db.query(CheckItem).filter(CheckItem.session_id == session_id).all()
    check_item_ids = [item.id for item in check_items]
    match_results = db.query(MatchResult).filter(MatchResult.check_item_id.in_(check_item_ids)).all()
    
    # Convert SQLAlchemy items to dicts
    items_a = []
    for item in check_items:
        items_a.append({
            "id": str(item.id),
            "label": str(item.label),
            "value": cast(float, item.value),
            "unit": str(item.unit),
            "page": cast(int, item.page),
            "bbox": cast(dict | None, item.bbox),
            "context": str(item.context)
        })
        
    results = []
    for r in match_results:
        check_item = db.query(CheckItem).filter(CheckItem.id == r.check_item_id).first()
        if not check_item:
            continue
        
        s_label = ""
        s_value = 0.0
        s_unit = ""
        s_page = 0
        
        if r.source_item_id:
            s_item = db.query(SourceItem).filter(SourceItem.id == r.source_item_id).first()
            if s_item:
                s_label = str(s_item.label)
                s_value = cast(float, s_item.value)
                s_unit = str(s_item.unit)
                s_page = cast(int, s_item.page)
                
        results.append({
            "check_item_id": str(r.check_item_id),
            "matched": r.status == "approved",
            "confidence": cast(float, r.confidence),
            "ai_reasoning": str(r.ai_reasoning),
            "matched_source_label": s_label,
            "matched_source_value": s_value,
            "matched_source_unit": s_unit,
            "matched_source_page": s_page
        })
        
    base_dir = Path(__file__).resolve().parent.parent.parent
    uploads_dir = base_dir / "uploads"
    output_filename = f"{session_id}_annotated.pdf"
    output_path = uploads_dir / output_filename
    
    try:
        annotate_pdf_file_a(pdf_path, items_a, results, output_path)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to annotate PDF: {e}"
        )
        
    # Set session status to exported
    setattr(session, "status", "exported")
    db.commit()
    
    return FileResponse(
        path=output_path,
        media_type="application/pdf",
        filename="annotated_file_a.pdf"
    )
