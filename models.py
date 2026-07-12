from sqlalchemy import Column, Integer, String, Text, Float, Date, DateTime, ForeignKey, Boolean, UniqueConstraint, text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=True)
    openid = Column(String(100), unique=True, index=True, nullable=False)
    email = Column(String(200), unique=True, nullable=True)  # 加密存储
    phone = Column(String(200), unique=True, nullable=True)  # 加密存储
    email_hash = Column(String(64), unique=True, nullable=True, index=True)  # SHA-256，用于查询
    phone_hash = Column(String(64), unique=True, nullable=True, index=True)  # SHA-256，用于查询
    password = Column(String(200), default="")  # bcrypt 哈希
    nickname = Column(String(50), default="")
    avatar = Column(String(200), default="")
    bio = Column(String(500), default="")  # 个人简介
    gender = Column(String(10), default="")  # 性别
    birthday = Column(String(20), default="")  # 生日
    location = Column(String(100), default="")  # 所在地
    balance = Column(Float, default=0.0)
    trust_score = Column(Float, default=100.0)  # 信任分 0-100
    level_id = Column(Integer, ForeignKey("user_levels.id"), default=5)
    is_muted = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, server_default=text("'2027-07-09 00:00:00'"), comment="使用期限")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    @classmethod
    def by_email(cls, db, email: str):
        """通过邮箱查找用户（使用哈希匹配）"""
        from encryption_utils import hash_for_lookup
        h = hash_for_lookup(email)
        return db.query(cls).filter(cls.email_hash == h).first() if h else None

    @classmethod
    def by_phone(cls, db, phone: str):
        """通过手机号查找用户（使用哈希匹配）"""
        from encryption_utils import hash_for_lookup
        h = hash_for_lookup(phone)
        return db.query(cls).filter(cls.phone_hash == h).first() if h else None

    @classmethod
    def by_email_or_phone(cls, db, value: str):
        """通过邮箱或手机号查找用户"""
        user = cls.by_email(db, value)
        if not user:
            user = cls.by_phone(db, value)
        return user


class Recipe(Base):
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(100), nullable=False)
    recipe_no = Column(String(10), unique=True, index=True, nullable=True)  # 编号：A001-Z999
    type = Column(String(20), default="recipe")  # recipe / firing / matching
    cover = Column(String(200), default="")
    images = Column(Text, default="[]")  # JSON: 多图URL，烧制作品/找配方参考图
    describe = Column(Text, default="")
    category = Column(String(30), default="")
    temperature = Column(String(30), default="")
    atmosphere = Column(String(20), default="")
    kiln_type = Column(String(30), default="")  # 电窑 / 气窑 / 柴窑 / 乐烧
    kiln_type_other = Column(String(50), default="")  # 自定义窑炉类型
    body_material = Column(String(30), default="")  # 坯体料类型
    price = Column(Integer, default=0)  # 分，0=免费
    # 烧制服务专用
    turnaround = Column(String(50), default="")  # 周转时间，如"3-5天"
    # 找配方专用
    reward = Column(Integer, default=0)  # 悬赏金额（分）
    contact = Column(String(200), default="")  # 联系方式/咸鱼链接
    visibility = Column(String(20), default="private")
    likes = Column(Integer, default=0)
    sold_count = Column(Integer, default=0)
    work_count = Column(Integer, default=0, nullable=False)  # 关联作品数量
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)  # 编辑时手动设置，不用 onupdate

    forked_from = Column(Integer, nullable=True)  # 二次改造来源配方ID
    source = Column(String(20), default="")  # 来源：glazy, etc.
    source_id = Column(String(50), default="")  # 来源原始ID
    surface = Column(String(30), default="")  # 釉面质感
    transparency = Column(String(30), default="")  # 透明度
    glaze_colors = Column(Text, default="[]")  # JSON: [{hex, r, g, b, name}]
    color = Column(String(50), default="")  # 釉色名称


class Purchase(Base):
    """购买/交易记录"""
    __tablename__ = "purchases"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=True)
    work_id = Column(Integer, ForeignKey("works.id"), nullable=True)
    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    seller_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Integer, nullable=False)
    status = Column(String(20), default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    confirmed_at = Column(DateTime(timezone=True), nullable=True)


class Review(Base):
    """评价"""
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, ForeignKey("reviews.id"), nullable=True)
    purchase_id = Column(Integer, ForeignKey("purchases.id"), nullable=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=True)
    work_id = Column(Integer, ForeignKey("works.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    rating = Column(Integer, default=5)
    content = Column(Text, default="")
    image = Column(String(200), default="")
    body_material = Column(String(30), default="")  # 坯体料
    kiln_type = Column(String(30), default="")  # 窑类型
    kiln_type_other = Column(String(50), default="")
    temperature = Column(String(30), default="")  # 烧成温度
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    replies = relationship("Review", backref="parent", remote_side=[id], lazy="selectin")


class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=True)
    work_id = Column(Integer, ForeignKey("works.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class UserMaterial(Base):
    """用户材料库存 & 待购清单（status区分）"""
    __tablename__ = "user_materials"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)
    category = Column(String(50), default="")
    status = Column(String(10), default="owned")  # 'owned' 或 'wishlist'
    from_recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=True)
    work_id = Column(Integer, ForeignKey("works.id"), nullable=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FiringCurve(Base):
    """烧制曲线"""
    __tablename__ = "firing_curves"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True, comment="所属用户，null=系统默认")
    name = Column(String(100), nullable=False)
    type = Column(String(20), default="氧化")  # 氧化 / 还原
    target_temp = Column(String(20), default="")  # 目标温度，如"1220℃"
    segments = Column(Text, default="[]")  # JSON: 升温段 [{rate, temp, hold}]
    description = Column(Text, default="")
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Work(Base):
    """作品（烧制结果/纯图展示）"""
    __tablename__ = "works"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=True)  # 可选关联配方
    image = Column(Text, nullable=False)  # 作品主图
    images = Column(Text, default="[]")  # JSON 数组：多图URL
    description = Column(Text, default="")
    body_material = Column(String(30), default="")
    kiln_type = Column(String(30), default="")
    kiln_type_other = Column(String(50), default="")
    temperature = Column(String(30), default="")
    likes = Column(Integer, default=0)
    glaze_colors = Column(Text, default="[]")  # JSON: [{hex, r, g, b, name}]
    surface = Column(String(20), default="")  # 釉面质感：亮光/丝光/蜡光/柔光/无光/磨砂
    transparency = Column(String(20), default="")  # 透明度：高透/微透/半透/不透
    curve_id = Column(Integer, ForeignKey("firing_curves.id"), nullable=True)  # 关联烧制曲线
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class WorkComment(Base):
    """作品评论"""
    __tablename__ = "work_comments"

    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, ForeignKey("work_comments.id"), nullable=True)
    work_id = Column(Integer, ForeignKey("works.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Follow(Base):
    """用户关注"""
    __tablename__ = "follows"

    id = Column(Integer, primary_key=True, index=True)
    follower_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    followed_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RecipeView(Base):
    """配方浏览记录"""
    __tablename__ = "recipe_views"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RecipeIngredient(Base):
    """配方配料表"""
    __tablename__ = "recipe_ingredients"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False, index=True)
    recipe_no = Column(String(10), default="")
    name = Column(String(200), nullable=False, default="")  # AES 加密存储
    name_en = Column(String(200), default="")
    name_hash = Column(String(64), default="", index=True)  # SHA-256，用于搜索匹配
    amount = Column(String(100), default="")  # AES 加密存储
    unit = Column(String(20), default="")  # g / %
    note = Column(Text)
    is_additional = Column(Integer, default=0)  # 是否附加 0=否 1=是
    sort_order = Column(Integer, default=0)


class IngredientName(Base):
    """公开配料名索引（明文，仅用于搜索下拉列表）"""
    __tablename__ = "ingredient_names"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), unique=True, nullable=False)


class Like(Base):
    """点赞记录（通用：配方/作品）"""
    __tablename__ = "likes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=True)
    work_id = Column(Integer, ForeignKey("works.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    """私信消息"""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    receiver_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=True)
    work_id = Column(Integer, ForeignKey("works.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_read = Column(Boolean, default=False)


class Complaint(Base):
    """User feedback / complaint record."""
    __tablename__ = "complaints"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    images = Column(Text, default="")
    status = Column(String(20), default="open")
    reply = Column(Text, default="")
    admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    replied_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class WorkAttributeOption(Base):
    """作品属性可选值（后台配置）"""
    __tablename__ = "work_attribute_options"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(30), nullable=False, index=True)  # type / body_material / kiln_type / temperature / surface / transparency
    value = Column(String(50), nullable=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class GlossaryTerm(Base):
    """陶瓷术语表（附属/名词解释）"""
    __tablename__ = "glossary_terms"

    id = Column(Integer, primary_key=True, index=True)
    term = Column(String(100), nullable=False, index=True)
    definition = Column(Text, nullable=False)
    category = Column(String(50), default="")
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TemperatureCone(Base):
    """奥尔顿测温锥温度对照表（附录8）"""
    __tablename__ = "temperature_cones"

    id = Column(Integer, primary_key=True, index=True)
    cone_no = Column(String(10), nullable=False, index=True)   # 温锥号，如 09, 1, 14
    temp_60c = Column(Integer, default=0)    # 60°C/h 温度
    temp_108f = Column(Integer, default=0)   # 108°F/h 温度
    temp_150c = Column(Integer, default=0)   # 150°C/h 温度
    temp_270f = Column(Integer, default=0)   # 270°F/h 温度
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Material(Base):
    """合并后的原材料统一表（本土+海外）"""
    __tablename__ = "materials"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, index=True)        # 中文名
    name_en = Column(String(200), default="")                      # 英文名
    source = Column(String(20), default="")                        # 'local' 或 'glazy'
    source_id = Column(Integer, nullable=True)                     # glazy_id（来源glazy时）
    formula = Column(String(200), default="")                      # 分子式
    molecular_weight = Column(String(50), default="")              # 分子量
    is_analysis = Column(Integer, default=0)
    is_primitive = Column(Integer, default=0)
    # 氧化物成分（重量百分比 %）
    sio2 = Column(Float, nullable=True)
    al2o3 = Column(Float, nullable=True)
    fe2o3 = Column(Float, nullable=True)
    tio2 = Column(Float, nullable=True)
    cao = Column(Float, nullable=True)
    mgo = Column(Float, nullable=True)
    na2o = Column(Float, nullable=True)
    k2o = Column(Float, nullable=True)
    zno = Column(Float, nullable=True)
    b2o3 = Column(Float, nullable=True)
    p2o5 = Column(Float, nullable=True)
    li2o = Column(Float, nullable=True)
    mno2 = Column(Float, nullable=True)
    coo = Column(Float, nullable=True)
    sno2 = Column(Float, nullable=True)
    cuo = Column(Float, nullable=True)
    cr2o3 = Column(Float, nullable=True)
    pbo = Column(Float, nullable=True)
    bao = Column(Float, nullable=True)
    sro = Column(Float, nullable=True)
    loi = Column(Float, nullable=True)
    thermal_expansion = Column(Float, nullable=True)
    category = Column(String(50), default="")
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CeramicMaterial(Base):
    """陶瓷原材料清单（附录1）"""
    __tablename__ = "ceramic_materials"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)       # 原材料名
    name_en = Column(String(100), default="")                      # 英文名
    formula = Column(String(200), default="")                     # 分子式（Unicode下标）
    molecular_weight = Column(String(50), default="")            # 分子量
    # 氧化物成分（重量百分比 %）
    sio2 = Column(Float, nullable=True)
    al2o3 = Column(Float, nullable=True)
    fe2o3 = Column(Float, nullable=True)
    tio2 = Column(Float, nullable=True)
    cao = Column(Float, nullable=True)
    mgo = Column(Float, nullable=True)
    na2o = Column(Float, nullable=True)
    k2o = Column(Float, nullable=True)
    zno = Column(Float, nullable=True)
    b2o3 = Column(Float, nullable=True)
    p2o5 = Column(Float, nullable=True)
    loi = Column(Float, nullable=True)  # 烧失量
    category = Column(String(50), default="")
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RecipeSeger(Base):
    """配方 Seger 公式计算结果"""
    __tablename__ = "recipe_seger"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False, unique=True)
    seger_unified = Column(String(500), default="")       # 归一化表达式
    seger_al2o3 = Column(Float, nullable=True)             # Al₂O₃ 摩尔比
    seger_sio2 = Column(Float, nullable=True)              # SiO₂ 摩尔比
    seger_ro = Column(Float, nullable=True)                # RO+R₂O 总和
    acid_base_ratio = Column(Float, nullable=True)         # SiO₂/Al₂O₃
    acid_base_note = Column(String(500), default="")
    seger_detail = Column(Text, default="")                # JSON: 各氧化物摩尔明细
    calculated_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    recipe = relationship("Recipe", backref="seger")


class MaterialSubstitution(Base):
    """材料替换关联表"""
    __tablename__ = "material_substitutions"

    id = Column(Integer, primary_key=True, index=True)
    source_material_id = Column(Integer, ForeignKey("materials.id"), nullable=False, comment="源材料（需要被替换的）")
    target_material_id = Column(Integer, ForeignKey("materials.id"), nullable=False, comment="目标材料（替换建议）")
    similarity_score = Column(Float, default=0.0, comment="成分相似度 0-100")
    status = Column(String(20), default="pending", comment="pending/confirmed/ignored")
    note = Column(String(500), default="", comment="替换备注（如用量调整建议）")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    source_material = relationship("Material", foreign_keys=[source_material_id])
    target_material = relationship("Material", foreign_keys=[target_material_id])


class UserLevel(Base):
    """用户等级"""
    __tablename__ = "user_levels"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    max_paid_recipes = Column(Integer, default=0)
    max_free_recipes = Column(Integer, default=10)
    max_works = Column(Integer, default=50)
    max_views = Column(Integer, default=0, comment="每日可查看配方上限，0=禁止查看")
    description = Column(String(200), default="")
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class UserUsageQuota(Base):
    """用户当日功能剩余额度及累计兑换次数。"""
    __tablename__ = "user_usage_quotas"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    quota_date = Column(Date, nullable=False, index=True)
    paid_recipe_remaining = Column(Integer, nullable=False, default=0)
    free_recipe_remaining = Column(Integer, nullable=False, default=0)
    work_remaining = Column(Integer, nullable=False, default=0)
    recipe_view_remaining = Column(Integer, nullable=False, default=0)
    redeem_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UserDailyRecipeView(Base):
    """同一用户同一配方同一天仅消耗一次查看额度。"""
    __tablename__ = "user_daily_recipe_views"
    __table_args__ = (
        UniqueConstraint("user_id", "recipe_id", "view_date", name="uq_user_recipe_view_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False, index=True)
    view_date = Column(Date, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ToBeFired(Base):
    """待烧（用户计划烧制的配方队列）"""
    __tablename__ = "to_be_fired"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=True, index=True)
    note = Column(String(200), default="")  # 备注（如"用XX泥"）
    status = Column(String(20), default="pending")  # pending / firing / done
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Notification(Base):
    """系统通知"""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    from_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    type = Column(String(32), nullable=False)  # comment / follow / like / favorite
    work_id = Column(Integer, ForeignKey("works.id"), nullable=True)
    content = Column(Text, default="")
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RecipeSequence(Base):
    """配方编号计数器（行锁保证并发唯一）"""
    __tablename__ = "recipe_sequences"

    letter = Column(String(1), primary_key=True)  # A-Z
    counter = Column(Integer, nullable=False, default=0)
    digits = Column(Integer, nullable=False, default=3)  # 当前位数：3→999，4→9999，5→99999


class UserSettings(Base):
    """用户默认设置（新建配方/作品时自动带入）"""
    __tablename__ = "user_settings"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    materials = Column(Text, default="[]")        # JSON: ["高岭土","长石",...]
    kiln_types = Column(Text, default="[]")       # JSON: ["电窑","气窑"]
    temperatures = Column(Text, default="[]")     # JSON: ["1220℃","1280℃"]
    firing_curve_id = Column(Integer, ForeignKey("firing_curves.id"), nullable=True)
    body_material = Column(String(50), default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AppSetting(Base):
    """Application-level key/value settings."""
    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, default="")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WalletTransaction(Base):
    """钱包交易记录"""
    __tablename__ = "wallet_transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=True)
    type = Column(String(20), nullable=False)  # deposit / withdraw / spending
    amount = Column(Integer, nullable=False)  # 分（正数）
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RecipeVersion(Base):
    """配方历史版本快照"""
    __tablename__ = "recipe_versions"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False, index=True)
    version_no = Column(Integer, nullable=False)  # 1, 2, 3...
    recipe_data = Column(Text, nullable=False)  # JSON: recipe 表所有字段
    ingredients_data = Column(Text, nullable=False)  # JSON: ingredients 列表
    seger_data = Column(Text, nullable=True)  # JSON: seger 结果
    note = Column(String(200), default="")  # 自动生成的备注
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class GlazyMaterial(Base):
    """Glazy 海外材料数据"""
    __tablename__ = "glazy_materials"

    glazy_id = Column(Integer, primary_key=True, autoincrement=False)
    name = Column(String(200), nullable=False, index=True)
    name_cn = Column(String(200), default="")
    is_analysis = Column(Integer, default=0)
    is_primitive = Column(Integer, default=0)
    sio2 = Column(Float, nullable=True)
    al2o3 = Column(Float, nullable=True)
    na2o = Column(Float, nullable=True)
    k2o = Column(Float, nullable=True)
    mgo = Column(Float, nullable=True)
    cao = Column(Float, nullable=True)
    fe2o3 = Column(Float, nullable=True)
    tio2 = Column(Float, nullable=True)
    zno = Column(Float, nullable=True)
    b2o3 = Column(Float, nullable=True)
    p2o5 = Column(Float, nullable=True)
    loi = Column(Float, nullable=True)


class RedeemCode(Base):
    """兑换码"""
    __tablename__ = "redeem_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(32), unique=True, index=True, nullable=False, comment="兑换码")
    days = Column(Integer, nullable=False, comment="可兑换天数")
    max_uses = Column(Integer, default=1, comment="最大使用次数")
    current_uses = Column(Integer, default=0, comment="已使用次数")
    is_active = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RedeemLog(Base):
    """兑换记录"""
    __tablename__ = "redeem_logs"

    id = Column(Integer, primary_key=True, index=True)
    code_id = Column(Integer, ForeignKey("redeem_codes.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    days_added = Column(Integer, nullable=False)
    before_expiry = Column(DateTime(timezone=True), nullable=True, comment="兑换前使用期限")
    after_expiry = Column(DateTime(timezone=True), nullable=True, comment="兑换后使用期限")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
