from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db
from models import User, Purchase, Recipe, WalletTransaction


class BuyRequest(BaseModel):
    recipe_id: int

router = APIRouter(prefix="/wallet", tags=["钱包"])


def _balance_payload(user: User):
    return {
        "balance": user.balance or 0,
        "unit": "币",
    }


@router.get("")
def get_wallet(user_id: int = Query(...), db: Session = Depends(get_db)):
    """Compatibility endpoint for the miniprogram wallet page."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _balance_payload(user)


@router.get("/balance")
def get_balance(user_id: int = Query(...), db: Session = Depends(get_db)):
    """查看余额（币）"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _balance_payload(user)


@router.post("/recharge")
def recharge(
    user_id: int = Query(...),
    amount: float = Query(...),
    db: Session = Depends(get_db),
):
    if amount <= 0:
        raise HTTPException(status_code=400, detail="充值金额必须大于0")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.balance = (user.balance or 0) + amount
    # 创建充值记录
    tx = WalletTransaction(user_id=user_id, type="deposit", amount=int(amount))
    db.add(tx)
    db.commit()
    db.refresh(user)
    return _balance_payload(user)


@router.post("/create-order")
def create_order(data: dict, db: Session = Depends(get_db)):
    """Development placeholder for real WeChat Pay integration."""
    user_id = data.get("user_id")
    amount = data.get("amount")
    if not user_id or not amount or float(amount) <= 0:
        raise HTTPException(status_code=400, detail="参数不完整")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {
        "mock": True,
        "timeStamp": "",
        "nonceStr": "",
        "package": "",
        "paySign": "",
    }


@router.get("/income")
def get_income(user_id: int = Query(...), db: Session = Depends(get_db)):
    """查看收入明细"""
    purchases = (
        db.query(Purchase)
        .filter(Purchase.seller_id == user_id, Purchase.status == "confirmed")
        .order_by(Purchase.created_at.desc())
        .all()
    )
    return [
        {
            "id": p.id,
            "recipe_id": p.recipe_id,
            "amount": p.amount,
            "unit": "币",
            "created_at": p.created_at.isoformat(),
        }
        for p in purchases
    ]


@router.get("/spending")
def get_spending(user_id: int = Query(...), db: Session = Depends(get_db)):
    """查看消费明细"""
    purchases = (
        db.query(Purchase)
        .filter(Purchase.buyer_id == user_id, Purchase.status == "confirmed")
        .order_by(Purchase.created_at.desc())
        .all()
    )
    result = []
    for p in purchases:
        recipe = db.query(Recipe).filter(Recipe.id == p.recipe_id).first()
        result.append({
            "id": p.id,
            "recipe_id": p.recipe_id,
            "title": recipe.title if recipe else "已删除",
            "amount": p.amount,
            "unit": "币",
            "created_at": p.created_at.isoformat(),
        })
    return result


@router.get("/history")
def get_history(user_id: int = Query(...), db: Session = Depends(get_db)):
    rows = []

    # 收入（卖出配方 → 收入）
    for item in get_income(user_id=user_id, db=db):
        recipe = db.query(Recipe).filter(Recipe.id == item["recipe_id"]).first()
        rows.append({
            **item,
            "type": "income",
            "title": recipe.title if recipe else "已删除",
            "recipe_id": item["recipe_id"],
        })

    # 消费（买入配方 → 消费）
    for item in get_spending(user_id=user_id, db=db):
        rows.append({**item, "type": "spending"})

    # 充值记录（存入）
    deposits = (
        db.query(WalletTransaction)
        .filter(WalletTransaction.user_id == user_id, WalletTransaction.type == "deposit")
        .order_by(WalletTransaction.created_at.desc())
        .all()
    )
    for tx in deposits:
        rows.append({
            "id": tx.id,
            "recipe_id": None,
            "title": "",
            "amount": tx.amount,
            "unit": "币",
            "created_at": tx.created_at.isoformat() if tx.created_at else "",
            "type": "deposit",
        })

    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return rows


@router.post("/buy")
def buy_recipe(data: BuyRequest, user_id: int = Query(...), db: Session = Depends(get_db)):
    """购买付费配方：扣余额+增卖家收入+创建交易记录"""
    buyer = db.query(User).filter(User.id == user_id).first()
    if not buyer:
        raise HTTPException(status_code=404, detail="用户不存在")

    recipe = db.query(Recipe).filter(Recipe.id == data.recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")

    price = recipe.price or 0
    if price <= 0:
        raise HTTPException(status_code=400, detail="该配方免费，无需购买")

    if buyer.id == recipe.user_id:
        raise HTTPException(status_code=400, detail="不能购买自己的配方")

    # 检查是否已购买
    existing = db.query(Purchase).filter(
        Purchase.recipe_id == data.recipe_id,
        Purchase.buyer_id == user_id,
        Purchase.status == "confirmed",
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="已购买过此配方")

    if (buyer.balance or 0) < price:
        raise HTTPException(status_code=400, detail=f"余额不足，需要 {price} 币，当前余额 {(buyer.balance or 0):.0f} 币")

    # 扣买家
    buyer.balance = (buyer.balance or 0) - price

    # 加卖家
    seller = db.query(User).filter(User.id == recipe.user_id).first()
    if seller:
        seller.balance = (seller.balance or 0) + price

    # 创建交易记录
    purchase = Purchase(
        recipe_id=data.recipe_id,
        buyer_id=user_id,
        seller_id=recipe.user_id,
        amount=price,
        status="confirmed",
    )
    db.add(purchase)

    # 增加配方销量
    recipe.sold_count = (recipe.sold_count or 0) + 1

    db.commit()
    db.refresh(purchase)

    return {
        "id": purchase.id,
        "recipe_id": purchase.recipe_id,
        "amount": purchase.amount,
        "status": purchase.status,
        "buyer_balance": buyer.balance,
    }
