import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.db.database import Base

class SourceDocument(Base):
    __tablename__ = "source_documents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String(255), nullable=False)
    title = Column(String(255), nullable=True)
    version = Column(String(50), nullable=True)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationship to source items
    items = relationship("SourceItem", back_populates="document", cascade="all, delete-orphan")


class SourceItem(Base):
    __tablename__ = "source_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String(36), ForeignKey("source_documents.id"), nullable=False)
    page = Column(Integer, nullable=False)
    label = Column(String(255), nullable=False)
    value = Column(Float, nullable=False)
    unit = Column(String(50), nullable=False)
    context_text = Column(String, nullable=False)
    bbox = Column(JSON, nullable=True)  # Store bounding box {x0, y0, x1, y1}
    category = Column(String(100), nullable=True)

    document = relationship("SourceDocument", back_populates="items")
    match_results = relationship("MatchResult", back_populates="source_item", cascade="all, delete-orphan")


class CheckSession(Base):
    __tablename__ = "check_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    file_a_path = Column(String(512), nullable=False)
    prompt_template_id = Column(String(36), ForeignKey("prompt_templates.id"), nullable=True)
    status = Column(String(50), default="pending")  # pending, reviewed, exported
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    check_items = relationship("CheckItem", back_populates="session", cascade="all, delete-orphan")
    prompt_template = relationship("PromptTemplate", back_populates="sessions")


class CheckItem(Base):
    __tablename__ = "check_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("check_sessions.id"), nullable=False)
    label = Column(String(255), nullable=False)
    value = Column(Float, nullable=False)
    unit = Column(String(50), nullable=False)
    bbox = Column(JSON, nullable=True)  # Store bounding box {x0, y0, x1, y1}
    page = Column(Integer, nullable=False)
    context = Column(String, nullable=False)
    source_hint = Column(String(255), nullable=True)
    category = Column(String(100), nullable=True)

    session = relationship("CheckSession", back_populates="check_items")
    match_results = relationship("MatchResult", back_populates="check_item", cascade="all, delete-orphan")


class MatchResult(Base):
    __tablename__ = "match_results"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    check_item_id = Column(String(36), ForeignKey("check_items.id"), nullable=False)
    source_item_id = Column(String(36), ForeignKey("source_items.id"), nullable=True)
    confidence = Column(Float, nullable=False)
    status = Column(String(50), default="pending")  # approved, rejected, pending
    ai_reasoning = Column(String, nullable=False)
    reviewed_by = Column(String(100), nullable=True)

    check_item = relationship("CheckItem", back_populates="match_results")
    source_item = relationship("SourceItem", back_populates="match_results")


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    content = Column(String, nullable=False)
    industry = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    sessions = relationship("CheckSession", back_populates="prompt_template")
