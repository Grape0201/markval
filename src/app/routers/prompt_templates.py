from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import uuid
from datetime import datetime, timezone
from pydantic import BaseModel

from app.db.database import get_db
from app.db.models import PromptTemplate

router = APIRouter(prefix="/api/v1/prompt-templates", tags=["prompt-templates"])

class PromptTemplateBase(BaseModel):
    name: str
    content: str
    industry: str | None = None

class PromptTemplateCreate(PromptTemplateBase):
    pass

class PromptTemplateUpdate(PromptTemplateBase):
    pass

class PromptTemplateResponse(PromptTemplateBase):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=list[PromptTemplateResponse])
def list_templates(db: Session = Depends(get_db)):
    templates = db.query(PromptTemplate).all()
    return templates


@router.get("/{template_id}", response_model=PromptTemplateResponse)
def get_template(template_id: str, db: Session = Depends(get_db)):
    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Prompt template with id {template_id} not found"
        )
    return template


@router.post("", response_model=PromptTemplateResponse, status_code=status.HTTP_201_CREATED)
def create_template(template_in: PromptTemplateCreate, db: Session = Depends(get_db)):
    template = PromptTemplate(
        id=str(uuid.uuid4()),
        name=template_in.name,
        content=template_in.content,
        industry=template_in.industry,
        created_at=datetime.now(timezone.utc)
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.put("/{template_id}", response_model=PromptTemplateResponse)
def update_template(template_id: str, template_in: PromptTemplateUpdate, db: Session = Depends(get_db)):
    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Prompt template with id {template_id} not found"
        )
    
    setattr(template, "name", template_in.name)
    setattr(template, "content", template_in.content)
    setattr(template, "industry", template_in.industry)
    
    db.commit()
    db.refresh(template)
    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: str, db: Session = Depends(get_db)):
    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Prompt template with id {template_id} not found"
        )
    db.delete(template)
    db.commit()
    return None
