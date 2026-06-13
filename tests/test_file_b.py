import io
from unittest.mock import AsyncMock, patch
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.main import app
from app.db.models import SourceDocument

# Test database setup
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_markval.db"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(name="db_session")
def fixture_db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(name="client")
def fixture_client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@patch("app.routers.file_b.extract_source_items_from_pdf", new_callable=AsyncMock)
def test_upload_source_document_duplicate(mock_extract, client, db_session):
    # Mock return value of PDF extraction to avoid calling LLM/PDF extraction
    mock_extract.return_value = []

    file_content = b"Dummy PDF content for hashing testing"
    file_name = "test_document.pdf"
    
    # 1. First upload should succeed (201 Created)
    response1 = client.post(
        "/api/v1/source-documents",
        files={"file": (file_name, io.BytesIO(file_content), "application/pdf")},
        data={"title": "Test Document", "version": "1.0"}
    )
    assert response1.status_code == 201
    data1 = response1.json()
    assert data1["filename"] == file_name

    # Verify document is saved in DB with a hash
    doc = db_session.query(SourceDocument).filter(SourceDocument.id == data1["id"]).first()
    assert doc is not None
    assert doc.file_hash is not None

    # 2. Second upload with the same content should fail (409 Conflict)
    response2 = client.post(
        "/api/v1/source-documents",
        files={"file": (file_name, io.BytesIO(file_content), "application/pdf")},
        data={"title": "Test Document Duplicate", "version": "1.0"}
    )
    assert response2.status_code == 409
    assert "既に登録されています" in response2.json()["detail"]

    # 3. Third upload with different content should succeed (201 Created)
    different_content = b"Different dummy PDF content"
    response3 = client.post(
        "/api/v1/source-documents",
        files={"file": (file_name, io.BytesIO(different_content), "application/pdf")},
        data={"title": "Different Document", "version": "1.0"}
    )
    assert response3.status_code == 201


@patch("app.routers.file_b.extract_source_items_from_pdf", new_callable=AsyncMock)
def test_upload_source_document_with_categories(mock_extract, client, db_session):
    mock_extract.return_value = []
    file_content = b"Dummy PDF content for categories testing"
    file_name = "test_categories.pdf"
    
    # Upload with categories
    response = client.post(
        "/api/v1/source-documents",
        files={"file": (file_name, io.BytesIO(file_content), "application/pdf")},
        data={
            "title": "Test Categories Document", 
            "version": "1.0",
            "categories": "固定荷重,  積載荷重"
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["filename"] == file_name
    assert data["categories"] == ["固定荷重", "積載荷重"]

    # Verify database record
    doc = db_session.query(SourceDocument).filter(SourceDocument.id == data["id"]).first()
    assert doc is not None
    assert doc.categories == ["固定荷重", "積載荷重"]

    # Verify GET list response
    list_response = client.get("/api/v1/source-documents")
    assert list_response.status_code == 200
    list_data = list_response.json()
    matched_doc = next((d for d in list_data if d["id"] == data["id"]), None)
    assert matched_doc is not None
    assert matched_doc["categories"] == ["固定荷重", "積載荷重"]


@patch("app.routers.file_b.annotate_pdf_file_b_extracted")
@patch("app.routers.file_b.extract_source_items_from_pdf", new_callable=AsyncMock)
def test_export_extracted_source_pdf(mock_extract, mock_annotate, client, db_session):
    mock_extract.return_value = [
        {
            "page": 1,
            "label": "Test Item B",
            "value": 12.3,
            "unit": "kN/m2",
            "context_text": "Dummy context",
            "bbox": {"x0": 10, "y0": 20, "x1": 30, "y1": 40},
            "category": "固定荷重"
        }
    ]
    file_content = b"Dummy PDF content"
    file_name = "test_doc_extracted.pdf"
    
    # 1. Upload
    response = client.post(
        "/api/v1/source-documents",
        files={"file": (file_name, io.BytesIO(file_content), "application/pdf")},
        data={"title": "Test Doc B", "version": "1.0"}
    )
    assert response.status_code == 201
    doc_id = response.json()["id"]

    # 2. Save dummy file to bypass exists() check
    base_dir = Path(__file__).resolve().parents[2]
    uploads_dir = base_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    dummy_pdf_path = uploads_dir / f"{doc_id}.pdf"
    dummy_pdf_path.write_bytes(file_content)

    dummy_output_path = uploads_dir / f"extracted_{doc_id}.pdf"

    def create_dummy_output(*args, **kwargs):
        out_path = args[2]
        out_path.write_bytes(b"Dummy annotated PDF content")

    mock_annotate.side_effect = create_dummy_output

    try:
        # Call export endpoint
        export_response = client.get(f"/api/v1/source-documents/{doc_id}/export-extracted")
        assert export_response.status_code == 200
        assert export_response.headers["content-type"] == "application/pdf"
        assert "extracted_" in export_response.headers["content-disposition"]
        
        # Verify annotator was called
        mock_annotate.assert_called_once()
    finally:
        # Clean up
        if dummy_pdf_path.exists():
            dummy_pdf_path.unlink()
        if dummy_output_path.exists():
            dummy_output_path.unlink()

