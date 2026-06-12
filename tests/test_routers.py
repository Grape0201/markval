import io
import pytest
from unittest.mock import AsyncMock, patch, mock_open
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.main import app
from app.db.models import (
    CheckSession, CheckItem, MatchResult, SourceDocument, SourceItem
)

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_markval_routers.db"
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


# ==========================================
# Prompt Templates Router Tests
# ==========================================

def test_prompt_template_crud(client, db_session):
    # 1. List initially empty
    response = client.get("/api/v1/prompt-templates")
    assert response.status_code == 200
    assert response.json() == []

    # 2. Create template
    payload = {
        "name": "Standard Code Check",
        "content": "Check code guidelines.",
        "industry": "Architecture"
    }
    response = client.post("/api/v1/prompt-templates", json=payload)
    assert response.status_code == 201
    created = response.json()
    assert created["name"] == "Standard Code Check"
    assert "id" in created

    # 3. Get template by ID
    template_id = created["id"]
    response = client.get(f"/api/v1/prompt-templates/{template_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Standard Code Check"

    # 4. Get invalid ID template
    response = client.get("/api/v1/prompt-templates/invalid-id")
    assert response.status_code == 404

    # 5. Update template
    update_payload = {
        "name": "Updated Code Check",
        "content": "Check updated code guidelines.",
        "industry": "Civil"
    }
    response = client.put(f"/api/v1/prompt-templates/{template_id}", json=update_payload)
    assert response.status_code == 200
    assert response.json()["name"] == "Updated Code Check"

    # 6. Update invalid template
    response = client.put("/api/v1/prompt-templates/invalid-id", json=update_payload)
    assert response.status_code == 404

    # 7. Delete template
    response = client.delete(f"/api/v1/prompt-templates/{template_id}")
    assert response.status_code == 204

    # 8. Delete invalid template
    response = client.delete("/api/v1/prompt-templates/invalid-id")
    assert response.status_code == 404

    # 9. Verify gone
    response = client.get(f"/api/v1/prompt-templates/{template_id}")
    assert response.status_code == 404


# ==========================================
# File B (Source Documents) Router Tests
# ==========================================

def test_source_documents_endpoints(client, db_session):
    # Setup test data
    doc = SourceDocument(
        id="doc-123",
        filename="ref.pdf",
        title="Ref Doc",
        version="v1.0",
        file_hash="dummyhash123"
    )
    item = SourceItem(
        id="item-abc",
        document_id="doc-123",
        page=2,
        label="屋根固定荷重",
        value=1200.0,
        unit="N/m²",
        context_text="屋根の固定荷重は1200N/m²とする。",
        category="固定荷重"
    )
    db_session.add(doc)
    db_session.add(item)
    db_session.commit()

    # 1. List source documents
    response = client.get("/api/v1/source-documents")
    assert response.status_code == 200
    docs = response.json()
    assert len(docs) == 1
    assert docs[0]["id"] == "doc-123"
    assert docs[0]["item_count"] == 1

    # 2. Get source document items
    response = client.get("/api/v1/source-documents/doc-123/items")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["id"] == "item-abc"
    assert items[0]["label"] == "屋根固定荷重"

    # Get items for invalid doc
    response = client.get("/api/v1/source-documents/invalid-doc/items")
    assert response.status_code == 404

    # 3. Delete source document
    response = client.delete("/api/v1/source-documents/doc-123")
    assert response.status_code == 204

    # Delete invalid doc
    response = client.delete("/api/v1/source-documents/invalid-doc")
    assert response.status_code == 404

    # Verify deleted from DB
    assert db_session.query(SourceDocument).filter(SourceDocument.id == "doc-123").first() is None


# ==========================================
# File A (Sessions) Router Tests
# ==========================================

@pytest.mark.anyio
async def test_create_session(client, db_session):
    # Mock extract_check_items_from_pdf
    fake_items = [
        {
            "label": "Test Check Item",
            "value": 1500.0,
            "unit": "N/m²",
            "bbox": {"x0": 0.0, "y0": 0.0, "x1": 100.0, "y1": 20.0},
            "page": 1,
            "context": "床の固定荷重 1500 N/m²",
            "source_hint": "p.3",
            "category": "固定荷重"
        }
    ]

    with patch("app.routers.file_a.extract_check_items_from_pdf", new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = fake_items
        
        with patch("app.routers.file_a.open", mock_open(), create=True):
            file_content = b"Dummy PDF content for File A"
            response = client.post(
                "/api/v1/sessions",
                files={"file": ("file_a.pdf", io.BytesIO(file_content), "application/pdf")},
                data={"prompt_template_id": "temp-123", "categories": "固定荷重,積載荷重"}
            )
            
            assert response.status_code == 201
            res_data = response.json()
            assert res_data["status"] == "pending"
            assert res_data["item_count"] == 1
            assert "id" in res_data

            # Verify in DB
            sess = db_session.query(CheckSession).filter(CheckSession.id == res_data["id"]).first()
            assert sess is not None
            assert sess.prompt_template_id == "temp-123"

            items = db_session.query(CheckItem).filter(CheckItem.session_id == sess.id).all()
            assert len(items) == 1
            assert items[0].label == "Test Check Item"


def test_list_and_get_session_details(client, db_session):
    # Setup session & check items in DB
    sess = CheckSession(
        id="session-1",
        file_a_path="/path/to/file_a.pdf",
        prompt_template_id="temp-1",
        status="pending"
    )
    item = CheckItem(
        id="check-1",
        session_id="session-1",
        label="Test Item",
        value=1500.0,
        unit="N/m²",
        page=1,
        context="context info"
    )
    db_session.add(sess)
    db_session.add(item)
    db_session.commit()

    # 1. List sessions
    response = client.get("/api/v1/sessions")
    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 1
    assert sessions[0]["id"] == "session-1"
    assert sessions[0]["item_count"] == 1

    # 2. Get session items
    response = client.get("/api/v1/sessions/session-1/items")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["id"] == "check-1"

    response = client.get("/api/v1/sessions/invalid-session/items")
    assert response.status_code == 404


def test_session_results_endpoints(client, db_session):
    # Setup session, check item, source item, and match result in DB
    sess = CheckSession(id="session-1", file_a_path="/path/to/file_a.pdf", status="reviewed")
    c_item = CheckItem(id="check-1", session_id="session-1", label="Test Item", value=1500.0, unit="N/m²", page=1, context="context")
    s_item = SourceItem(id="source-1", document_id="doc-1", label="Ref Item", value=1500.0, unit="N/m²", page=2, context_text="ref context", category="固定荷重")
    result = MatchResult(id="result-1", check_item_id="check-1", source_item_id="source-1", confidence=0.95, status="approved", ai_reasoning="Matches perfectly.")
    db_session.add_all([sess, c_item, s_item, result])
    db_session.commit()

    # 1. Get session results
    response = client.get("/api/v1/sessions/session-1/results")
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["id"] == "result-1"
    assert results[0]["source_item"]["label"] == "Ref Item"

    response = client.get("/api/v1/sessions/invalid-session/results")
    assert response.status_code == 404

    # 2. Update result status
    response = client.patch("/api/v1/results/result-1", json={"status": "rejected"})
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["matched"] is False

    # Check DB update
    db_session.refresh(result)
    assert result.status == "rejected"

    # Invalid status patch
    response = client.patch("/api/v1/results/result-1", json={"status": "invalid-status"})
    assert response.status_code == 400

    # Invalid result ID patch
    response = client.patch("/api/v1/results/invalid-result", json={"status": "approved"})
    assert response.status_code == 404


def test_export_annotated_pdf(client, db_session):
    # Setup session, items, results
    sess = CheckSession(id="session-1", file_a_path="/path/to/file_a.pdf", status="reviewed")
    c_item = CheckItem(id="check-1", session_id="session-1", label="Test Item", value=1500.0, unit="N/m²", page=1, context="context")
    result = MatchResult(id="result-1", check_item_id="check-1", source_item_id=None, confidence=0.0, status="pending", ai_reasoning="Reason")
    db_session.add_all([sess, c_item, result])
    db_session.commit()

    with patch("app.routers.file_a.Path.exists") as mock_exists:
        mock_exists.return_value = True
        
        with patch("app.routers.file_a.annotate_pdf_file_a") as mock_annotate:
            # Mock annotate to prevent running actual PDF writer
            mock_annotate.return_value = None
            
            with patch("app.routers.file_a.FileResponse") as mock_fileresponse:
                mock_fileresponse.return_value = {"pdf": "dummy"}
                
                response = client.post("/api/v1/sessions/session-1/export")
                assert response.status_code == 200
                assert response.json() == {"pdf": "dummy"}
                mock_annotate.assert_called_once()

    # Invalid session export
    response = client.post("/api/v1/sessions/invalid-session/export")
    assert response.status_code == 404


# ==========================================
# Match Router Tests
# ==========================================

@pytest.mark.anyio
async def test_run_matching_endpoint(client, db_session):
    # Setup session and check item
    sess = CheckSession(id="session-1", file_a_path="/path/to/file_a.pdf", status="pending")
    c_item = CheckItem(id="check-1", session_id="session-1", label="Test Item", value=1500.0, unit="N/m²", page=1, context="context")
    db_session.add_all([sess, c_item])
    db_session.commit()

    # Mock match_check_item service
    mock_result = MatchResult(
        check_item_id="check-1",
        source_item_id="source-1",
        confidence=0.9,
        status="approved",
        ai_reasoning="LLM matches."
    )
    
    with patch("app.routers.match.match_check_item", new_callable=AsyncMock) as mock_match:
        mock_match.return_value = mock_result
        
        response = client.post("/api/v1/match", json={"session_id": "session-1", "document_ids": ["doc-1"]})
        assert response.status_code == 200
        results = response.json()
        assert len(results) == 1
        assert results[0]["check_item_id"] == "check-1"
        assert results[0]["status"] == "approved"

        # Check session status updated
        db_session.refresh(sess)
        assert sess.status == "reviewed"

    # Test run matching for session with no items
    sess2 = CheckSession(id="session-2", file_a_path="/path/to/file_a.pdf", status="pending")
    db_session.add(sess2)
    db_session.commit()

    response = client.post("/api/v1/match", json={"session_id": "session-2"})
    assert response.status_code == 400

    # Test run matching for invalid session
    response = client.post("/api/v1/match", json={"session_id": "invalid-session"})
    assert response.status_code == 404
