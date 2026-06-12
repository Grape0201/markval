from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Database path in the project root folder
BASE_DIR = Path(__file__).resolve().parents[3]
DATABASE_URL = f"sqlite:///{BASE_DIR / 'markval.db'}"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def initialize_database() -> None:
    """Create database tables if they do not already exist."""
    # Import models so that SQLAlchemy is aware of all mapped classes.
    from app.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
