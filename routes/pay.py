from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import Recipe, User, Purchase

router = APIRouter(prefix="/pay", tags=["支付"])


@router.post("/prepay")
def prepay(
    recipe_id: int = Query(...),
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """虚拟币支付（直接扣余额，不需要第三方支付）"""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")
    if recipe.user_id == user_id:
        raise HTTPException(status_code=400, detail="不能购买自己的配方")

    amount = recipe.price or 0
    if amount <= 0:
        raise HTTPException(status_code=400, detail="免费配方无需支付")

    user = db.query(User).filter(User.id == user_id).first()
    if not user or (user.balance or 0) < amount:
        raise HTTPException(status_code=400, detail=f"币不够，需要{amount}币，当前{user.balance or 0}币")

    return {
        "mock": True,
        "amount": amount,
        "unit": "币",
        "balance": user.balance or 0,
    }


@router.post("/confirm")
def confirm_payment(
    out_trade_no: str = Query(...),
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """余额支付确认（直接调购买接口即可）"""
    return {"message": "请调用 /recipes/buy 接口购买"}
