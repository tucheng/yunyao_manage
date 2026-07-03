from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class RecipeCreate(BaseModel):
    title: str
    type: str = "recipe"  # recipe / firing / matching
    cover: str = ""
    images: str = "[]"
    ingredients: str = "[]"
    steps: str = "[]"
    tips: str = ""
    category: str = ""
    temperature: str = ""
    atmosphere: str = ""
    kiln_type: str = ""
    kiln_type_other: str = ""
    body_material: str = ""
    tags: str = ""
    price: int = 0
    turnaround: str = ""
    reward: int = 0
    contact: str = ""
    visibility: str = "private"
    work_id: int = 0
    forked_from: Optional[int] = None


class RecipeUpdate(BaseModel):
    title: Optional[str] = None
    type: Optional[str] = None
    cover: Optional[str] = None
    images: Optional[str] = None
    ingredients: Optional[str] = None
    steps: Optional[str] = None
    tips: Optional[str] = None
    category: Optional[str] = None
    temperature: Optional[str] = None
    atmosphere: Optional[str] = None
    kiln_type: Optional[str] = None
    kiln_type_other: Optional[str] = None
    body_material: Optional[str] = None
    tags: Optional[str] = None
    price: Optional[int] = None
    turnaround: Optional[str] = None
    reward: Optional[int] = None
    contact: Optional[str] = None
    visibility: Optional[str] = None


class RecipeOut(BaseModel):
    id: int
    user_id: int
    title: str
    recipe_no: Optional[str] = ""
    type: str
    cover: str
    images: str
    ingredients: str
    steps: str
    tips: str
    category: str
    temperature: str
    atmosphere: str
    kiln_type: str = ""
    kiln_type_other: str = ""
    body_material: str = ""
    tags: str
    price: int
    turnaround: str
    reward: int
    contact: str
    visibility: str
    likes: int
    sold_count: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_favorited: bool = False
    is_purchased: bool = False
    forked_from: Optional[int] = None
    author_name: str = ""
    rating_avg: float = 0
    favorite_count: int = 0
    works_count: int = 0
    ingredient_statuses: dict = {}

    model_config = {"from_attributes": True}


class RecipeListItem(BaseModel):
    id: int
    user_id: int
    title: str
    type: str
    cover: str
    category: str
    temperature: str
    atmosphere: str = ""
    kiln_type: str = ""
    body_material: str = ""
    price: int
    reward: int
    visibility: str
    likes: int
    sold_count: int
    author_name: str = ""
    recipe_no: Optional[str] = ""
    avatar: str = ""
    work_image: str = ""
    work_count: int = 0
    favorite_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    code: str


class PurchaseCreate(BaseModel):
    recipe_id: int


class PurchaseOut(BaseModel):
    id: int
    recipe_id: int
    buyer_id: int
    seller_id: int
    amount: int
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ReviewCreate(BaseModel):
    purchase_id: int = 0
    recipe_id: int
    parent_id: int = 0
    rating: int = 5
    content: str = ""
    image: str = ""
    body_material: str = ""
    kiln_type: str = ""
    kiln_type_other: str = ""
    temperature: str = ""


class ReviewOut(BaseModel):
    id: int
    user_id: int
    parent_id: Optional[int] = None
    recipe_id: int
    rating: int
    content: str
    image: str = ""
    body_material: str = ""
    kiln_type: str = ""
    kiln_type_other: str = ""
    temperature: str = ""
    recipe_title: str = ""
    created_at: datetime
    username: str = ""
    replies: list["ReviewOut"] = []

    model_config = {"from_attributes": True}


class WorkCommentCreate(BaseModel):
    user_id: int = 0
    content: str
    parent_id: int = 0


class WorkCommentOut(BaseModel):
    id: int
    parent_id: Optional[int] = None
    work_id: int
    user_id: int
    content: str
    created_at: datetime
    nickname: str = ""
    replies: list["WorkCommentOut"] = []

    model_config = {"from_attributes": True}
