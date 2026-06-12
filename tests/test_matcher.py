import pytest
from unittest.mock import MagicMock, AsyncMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from langchain_core.runnables import RunnableLambda

from app.db.database import Base
from app.db.models import CheckItem, SourceItem, MatchResult
from app.services.matcher import match_check_item, SingleMatchResponse

# Test database setup
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_markval_matcher.db"
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


@pytest.mark.anyio
async def test_match_check_item_success(db_session):
    # 1. テストデータの作成
    source_item = SourceItem(
        id="source-1",
        document_id="doc-1",
        label="屋根 固定荷重",
        value=1200.0,
        unit="N/m²",
        page=3,
        context_text="屋根の固定荷重は1200N/m²とする。",
        category="固定荷重"
    )
    db_session.add(source_item)
    
    check_item = CheckItem(
        id="check-1",
        session_id="session-1",
        label="屋根 固定荷重",
        value=1200.0,
        unit="N/m²",
        page=2,
        context="屋根の固定荷重は 1200 N/m²",
        category="固定荷重",
        source_hint="p.3"
    )
    db_session.add(check_item)
    db_session.commit()

    # 2. Mock LLM の作成
    mock_llm = MagicMock()
    fake_response = SingleMatchResponse(
        matched=True,
        matched_source_index=0,
        confidence=0.95,
        ai_reasoning="項目と数値が完全に一致しました。"
    )
    mock_llm.with_structured_output.return_value = RunnableLambda(lambda x: fake_response)

    # 3. 実行
    result = await match_check_item(db_session, check_item, llm=mock_llm)

    # 4. 検証
    assert result.check_item_id == "check-1"
    assert result.source_item_id == "source-1"
    assert result.confidence == 0.95
    assert result.status == "approved"
    assert result.ai_reasoning == "項目と数値が完全に一致しました。"


@pytest.mark.anyio
async def test_match_check_item_no_candidates(db_session):
    # 1. テストデータの作成 (SourceItemは登録しない)
    check_item = CheckItem(
        id="check-1",
        session_id="session-1",
        label="屋根 固定荷重",
        value=1200.0,
        unit="N/m²",
        page=2,
        context="屋根の固定荷重は 1200 N/m²",
        category="固定荷重"
    )
    db_session.add(check_item)
    db_session.commit()

    # Mock LLM (呼ばれないはず)
    mock_llm = MagicMock()

    # 2. 実行
    result = await match_check_item(db_session, check_item, llm=mock_llm)

    # 3. 検証
    assert result.source_item_id is None
    assert result.confidence == 0.0
    assert result.status == "pending"
    assert "No reference items found" in result.ai_reasoning
    mock_llm.with_structured_output.assert_not_called()


@pytest.mark.anyio
async def test_match_check_item_llm_exception(db_session):
    # 1. テストデータの作成
    source_item = SourceItem(
        id="source-1",
        document_id="doc-1",
        label="屋根 固定荷重",
        value=1200.0,
        unit="N/m²",
        page=3,
        context_text="屋根の固定荷重は1200N/m²とする。",
        category="固定荷重"
    )
    db_session.add(source_item)
    
    check_item = CheckItem(
        id="check-1",
        session_id="session-1",
        label="屋根 固定荷重",
        value=1200.0,
        unit="N/m²",
        page=2,
        context="屋根の固定荷重は 1200 N/m²",
        category="固定荷重"
    )
    db_session.add(check_item)
    db_session.commit()

    # 2. LLM の Mock (例外を発生させる)
    mock_llm = MagicMock()
    
    def raise_exception(x):
        raise ValueError("LLM API connection error")
        
    mock_llm.with_structured_output.return_value = RunnableLambda(raise_exception)

    # 3. 実行
    result = await match_check_item(db_session, check_item, llm=mock_llm)

    # 4. 検証
    assert result.source_item_id is None
    assert result.confidence == 0.0
    assert result.status == "pending"
    assert "LLM match check failed due to exception" in result.ai_reasoning
