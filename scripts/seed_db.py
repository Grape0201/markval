"""
PYTHONPATH=src uv run python scripts/seed_db.py
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db.models import SourceDocument, SourceItem, CheckSession, CheckItem, MatchResult, PromptTemplate

def seed_data(db: Session) -> None:
    # Clear old data
    print("Clearing old data...")
    db.query(MatchResult).delete()
    db.query(CheckItem).delete()
    db.query(CheckSession).delete()
    db.query(SourceItem).delete()
    db.query(SourceDocument).delete()
    db.query(PromptTemplate).delete()
    db.commit()

    print("Inserting seed data...")

    # 1. PromptTemplate
    pt1 = PromptTemplate(
        id=str(uuid.uuid4()),
        name="建築構造設計基準 テンプレート",
        content="あなたは優秀な構造設計のAIエージェントです。提示された計算書の数値が、基準書などの出典データと合致しているか照合してください。",
        industry="建築構造",
        created_at=datetime.now(timezone.utc)
    )
    db.add(pt1)

    # 2. SourceDocument (File B)
    doc1 = SourceDocument(
        id=str(uuid.uuid4()),
        filename="jass5_2024.pdf",
        title="JASS 5 鉄筋コンクリート工事 (2024年版)",
        version="2024",
        uploaded_at=datetime.now(timezone.utc),
        file_hash="hash_jass5_2024_dummy",
        categories=["材料強度", "コンクリート品質"]
    )
    db.add(doc1)

    doc2 = SourceDocument(
        id=str(uuid.uuid4()),
        filename="bcj_design_2023.pdf",
        title="建築物の構造関係技術基準解説書 (2023年版)",
        version="2023",
        uploaded_at=datetime.now(timezone.utc),
        file_hash="hash_bcj_design_2023_dummy",
        categories=["固定荷重", "積載荷重", "風荷重"]
    )
    db.add(doc2)
    db.commit()  # Commit to persist IDs for relations

    # 3. SourceItem
    # doc1 (JASS 5)
    s_item1 = SourceItem(
        id=str(uuid.uuid4()),
        document_id=doc1.id,
        page=45,
        label="設計基準強度 Fc",
        value=24.0,
        unit="N/mm2",
        context_text="普通コンクリートの設計基準強度(Fc)は、特記のない限り24 N/mm2とする。",
        bbox={"x0": 100, "y0": 150, "x1": 400, "y1": 170},
        category="材料強度"
    )
    # doc2 (BCJ)
    s_item2 = SourceItem(
        id=str(uuid.uuid4()),
        document_id=doc2.id,
        page=120,
        label="住宅の居室の積載荷重",
        value=180.0,
        unit="kg/m2",
        context_text="建築基準法施行令第85条に基づく住宅の居室の積載荷重(構造計算用)は180 kg/m2とする。",
        bbox={"x0": 50, "y0": 200, "x1": 350, "y1": 220},
        category="積載荷重"
    )
    db.add_all([s_item1, s_item2])
    db.commit()

    # 4. CheckSession (File A)
    session1 = CheckSession(
        id=str(uuid.uuid4()),
        file_a_path="/Users/shotaro/work/markval/bench/sample_file_a_keisan.pdf",
        prompt_template_id=pt1.id,
        status="reviewed",
        created_at=datetime.now(timezone.utc)
    )
    db.add(session1)
    db.commit()

    # 5. CheckItem
    c_item1 = CheckItem(
        id=str(uuid.uuid4()),
        session_id=session1.id,
        label="コンクリート設計基準強度",
        value=24.0,
        unit="N/mm2",
        bbox={"x0": 120, "y0": 250, "x1": 380, "y1": 270},
        page=3,
        context="主要構造部には設計基準強度Fc=24 N/mm2の普通コンクリートを使用する。",
        source_hint="JASS 5",
        category="材料強度"
    )
    c_item2 = CheckItem(
        id=str(uuid.uuid4()),
        session_id=session1.id,
        label="居室の積載荷重 (計算書)",
        value=180.0,
        unit="kg/m2",
        bbox={"x0": 80, "y0": 400, "x1": 300, "y1": 420},
        page=5,
        context="床の構造計算における居室の積載荷重は 180 kg/m2 として設計を行う。",
        source_hint="施行令第85条",
        category="積載荷重"
    )
    db.add_all([c_item1, c_item2])
    db.commit()

    # 6. MatchResult
    m_res1 = MatchResult(
        id=str(uuid.uuid4()),
        check_item_id=c_item1.id,
        source_item_id=s_item1.id,
        confidence=0.98,
        status="approved",
        ai_reasoning="計算書のコンクリート設計基準強度 24 N/mm2 は、JASS 5の基準値 24 N/mm2 と完全に一致します。",
        reviewed_by="System"
    )
    m_res2 = MatchResult(
        id=str(uuid.uuid4()),
        check_item_id=c_item2.id,
        source_item_id=s_item2.id,
        confidence=1.0,
        status="approved",
        ai_reasoning="計算書の居室の積載荷重 180 kg/m2 は、建築関係技術基準解説書の基準値 180 kg/m2 と完全に一致します。",
        reviewed_by="System"
    )
    db.add_all([m_res1, m_res2])
    db.commit()

    print("Seed data successfully inserted!")

if __name__ == "__main__":
    session = SessionLocal()
    try:
        seed_data(session)
    finally:
        session.close()
