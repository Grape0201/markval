import sys
from pathlib import Path

# Add src directory to path to allow importing app module
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db.database import SessionLocal, initialize_database
from app.db.models import PromptTemplate
from app.routers import prompt_templates, file_b, file_a, match

# Load environment variables
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    db = SessionLocal()
    try:
        count = db.query(PromptTemplate).count()
        if count == 0:
            default_template = PromptTemplate(
                id=str(uuid.uuid4()),
                name="構造計算_標準",
                content=(
                    "あなたは構造計算書（ファイルA）から設計に使用した荷重・定数の入力値を抽出する専門家です。\n"
                    "入力されたページテキスト（Markdown形式）から、設計定数や設計荷重等の入力パラメータを抽出してください。\n\n"
                    "【抽出対象】\n"
                    "- 各部位の固定荷重（部位ごとの N/m² 値）\n"
                    "- 積載荷重（室用途・加重種別（床用、大梁・柱用、地震用）ごとの N/m² 値）\n"
                    "- 地震関連パラメータ（Co, Z, Rt, Ci 等の数値）\n"
                    "- 風荷重パラメータ（Vo, Gf, qp, Cf 等の数値）\n"
                    "- 材料強度（鋼材種別ごとの降伏点、引張強さ、長期許容応力度 ft の N/mm² 値）"
                ),
                industry="建築構造",
                created_at=datetime.now(timezone.utc)
            )
            db.add(default_template)
            db.commit()
            print("Seeded default prompt template successfully.")
    except Exception as e:
        print(f"Error seeding default prompt template: {e}")
    finally:
        db.close()
    yield

app = FastAPI(title="PDF Verification API", version="1.0.0", lifespan=lifespan)

# Setup CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(prompt_templates.router)
app.include_router(file_b.router)
app.include_router(file_a.router)
app.include_router(match.router)

# Serve static files
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def read_root():
    return FileResponse(static_dir / "index.html")
