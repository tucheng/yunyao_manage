from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app_config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def commit_or_conflict(db, detail: str = "数据已被其他请求修改，请重试") -> None:
    """Commit one request-level unit of work with consistent rollback semantics."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=detail) from exc
    except BaseException:
        db.rollback()
        raise
