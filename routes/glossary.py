"""陶瓷术语表 - 路由"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from database import get_db
from models import GlossaryTerm

router = APIRouter(prefix="/glossary", tags=["附属-术语表"])


@router.get("")
def list_terms(
    q: str = Query("", description="搜索关键词"),
    page_size: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """获取术语列表，支持搜索"""
    query = db.query(GlossaryTerm)
    if q:
        keyword = f"%{q}%"
        query = query.filter(
            or_(
                GlossaryTerm.term.ilike(keyword),
                GlossaryTerm.definition.ilike(keyword),
            )
        )
    total = query.count()
    terms = query.order_by(GlossaryTerm.sort_order, GlossaryTerm.id).limit(page_size).all()
    return {
        "terms": [
            {
                "id": t.id,
                "term": t.term,
                "definition": t.definition,
                "category": t.category,
            }
            for t in terms
        ],
        "total": total,
    }


@router.get("/{term_id}")
def get_term(term_id: int, db: Session = Depends(get_db)):
    term = db.query(GlossaryTerm).filter(GlossaryTerm.id == term_id).first()
    if not term:
        raise HTTPException(status_code=404, detail="术语不存在")
    return {
        "id": term.id,
        "term": term.term,
        "definition": term.definition,
        "category": term.category,
    }


@router.post("")
def create_term(data: dict, db: Session = Depends(get_db)):
    term = GlossaryTerm(
        term=data["term"],
        definition=data.get("definition", ""),
        category=data.get("category", ""),
        sort_order=data.get("sort_order", 0),
    )
    db.add(term)
    db.commit()
    db.refresh(term)
    return {"id": term.id, "message": "创建成功"}


@router.put("/{term_id}")
def update_term(term_id: int, data: dict, db: Session = Depends(get_db)):
    term = db.query(GlossaryTerm).filter(GlossaryTerm.id == term_id).first()
    if not term:
        raise HTTPException(status_code=404, detail="术语不存在")
    if "term" in data:
        term.term = data["term"]
    if "definition" in data:
        term.definition = data["definition"]
    if "category" in data:
        term.category = data.get("category", "")
    if "sort_order" in data:
        term.sort_order = data.get("sort_order", 0)
    db.commit()
    return {"message": "更新成功"}


@router.delete("/{term_id}")
def delete_term(term_id: int, db: Session = Depends(get_db)):
    term = db.query(GlossaryTerm).filter(GlossaryTerm.id == term_id).first()
    if not term:
        raise HTTPException(status_code=404, detail="术语不存在")
    db.delete(term)
    db.commit()
    return {"message": "删除成功"}
