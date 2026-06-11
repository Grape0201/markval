from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import cast
import uuid
from pydantic import BaseModel

from app.db.database import get_db
from app.db.models import CheckSession, CheckItem, MatchResult, SourceItem
from app.services.matcher import match_check_item
from app.routers.file_a import MatchResultResponse, SourceItemInfo

router = APIRouter(tags=["match"])

class MatchRequest(BaseModel):
    session_id: str


@router.post("/api/v1/match", response_model=list[MatchResultResponse])
def run_matching(payload: MatchRequest, db: Session = Depends(get_db)):
    session_id = payload.session_id
    session = db.query(CheckSession).filter(CheckSession.id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with id {session_id} not found"
        )
        
    check_items = db.query(CheckItem).filter(CheckItem.session_id == session_id).all()
    if not check_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No checklist items found for session {session_id}. Please upload File A first."
        )
        
    check_item_ids = [item.id for item in check_items]
    
    # 1. Clear existing results for these check items
    existing_results = db.query(MatchResult).filter(MatchResult.check_item_id.in_(check_item_ids)).all()
    for r in existing_results:
        db.delete(r)
    db.commit()
    
    # 2. Execute match for each item
    new_results = []
    for check_item in check_items:
        try:
            result = match_check_item(db, check_item)
            setattr(result, "id", str(uuid.uuid4()))
            db.add(result)
            new_results.append(result)
        except Exception as e:
            # Create a pending failure result so matching doesn't halt entirely
            failed_result = MatchResult(
                id=str(uuid.uuid4()),
                check_item_id=check_item.id,
                source_item_id=None,
                confidence=0.0,
                status="pending",
                ai_reasoning=f"Matching failed due to exception: {e}"
            )
            db.add(failed_result)
            new_results.append(failed_result)
            
    # Update session status
    setattr(session, "status", "reviewed")
    db.commit()
    
    # 3. Format and return results
    response_list = []
    for result in new_results:
        db.refresh(result)
        item = db.query(CheckItem).filter(CheckItem.id == result.check_item_id).first()
        if not item:
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
                    context_text=str(s_item.context_text)
                )
                
        response_list.append(MatchResultResponse(
            id=str(result.id),
            check_item_id=str(result.check_item_id),
            check_item_label=str(item.label),
            check_item_value=cast(float, item.value),
            check_item_unit=str(item.unit),
            check_item_page=cast(int, item.page),
            matched=bool(result.status == "approved"),
            confidence=cast(float, result.confidence),
            status=str(result.status),
            ai_reasoning=str(result.ai_reasoning),
            source_item=source_item
        ))
        
    return response_list
