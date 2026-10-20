from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings


class Base(DeclarativeBase):
    pass


database_url = settings.database_url
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
if database_url.startswith("sqlite"):
    db_file = database_url.removeprefix("sqlite:///")
    if db_file and db_file != ":memory:":
        Path(db_file).parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
