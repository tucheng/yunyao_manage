from sqlalchemy import Column, Integer, String, Text, Float, Date, DateTime, ForeignKey, Boolean, UniqueConstraint, CheckConstraint, Index, text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=True)
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
    trust_score = Column(Float, default=100.0)  # 信任分 0-100
    level_id = Column(Integer, ForeignKey("user_levels.id", ondelete="RESTRICT"), default=5)
    is_muted = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    token_version = Column(Integer, nullable=False, default=0, server_default=text("0"))
    expires_at = Column(DateTime(timezone=True), nullable=False, server_default=text("'2027-07-09 00:00:00'"), comment="使用期限")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    @classmethod
    def by_email(cls, db, email: str):
        """通过邮箱查找用户（使用哈希匹配）"""
        from security import hash_for_lookup
        h = hash_for_lookup(email)
        return db.query(cls).filter(cls.email_hash == h).first() if h else None

    @classmethod
    def by_phone(cls, db, phone: str):
        """通过手机号查找用户（使用哈希匹配）"""
        from security import hash_for_lookup
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
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
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
    body_material = Column(String(30), default="")  # 坯体料类型
    visibility = Column(String(20), default="private")
    likes = Column(Integer, default=0)
    work_count = Column(Integer, default=0, nullable=False)  # 关联作品数量
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)  # 编辑时手动设置，不用 onupdate

    forked_from = Column(Integer, nullable=True)  # 二次改造来源配方ID
    source = Column(String(20), default="")  # 外部数据来源标识
    source_id = Column(String(50), default="")  # 来源原始ID
    surface = Column(String(30), default="")  # 釉面质感
    transparency = Column(String(30), default="")  # 透明度
    glaze_colors = Column(Text, default="[]")  # JSON: [{hex, r, g, b, name}]
    curve_id = Column(Integer, ForeignKey("firing_curves.id", ondelete="SET NULL"), nullable=True)  # 可选关联烧制曲线


class Review(Base):
    """评价"""
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, ForeignKey("reviews.id", ondelete="CASCADE"), nullable=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=True)
    work_id = Column(Integer, ForeignKey("works.id", ondelete="CASCADE"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
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
    __table_args__ = (
        UniqueConstraint("user_id", "recipe_id", name="uq_favorite_user_recipe"),
        UniqueConstraint("user_id", "work_id", name="uq_favorite_user_work"),
        CheckConstraint("(recipe_id IS NULL) <> (work_id IS NULL)", name="ck_favorite_one_target"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=True)
    work_id = Column(Integer, ForeignKey("works.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class UserMaterial(Base):
    """用户材料库存 & 待购清单（status区分）"""
    __tablename__ = "user_materials"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    category = Column(String(50), default="")
    status = Column(String(10), default="owned")  # 'owned' 或 'wishlist'
    from_recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True)
    work_id = Column(Integer, ForeignKey("works.id", ondelete="SET NULL"), nullable=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FiringCurve(Base):
    """烧制曲线"""
    __tablename__ = "firing_curves"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True, comment="所属用户，null=系统默认")
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
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True)  # 可选关联配方
    image = Column(Text, nullable=False)  # 作品主图
    images = Column(Text, default="[]")  # JSON 数组：多图URL
    description = Column(Text, default="")
    category = Column(String(30), default="")
    atmosphere = Column(String(20), default="")
    body_material = Column(String(30), default="")
    kiln_type = Column(String(30), default="")
    temperature = Column(String(30), default="")
    likes = Column(Integer, default=0)
    glaze_colors = Column(Text, default="[]")  # JSON: [{hex, r, g, b, name}]
    surface = Column(String(20), default="")  # 釉面质感：亮光/丝光/蜡光/柔光/无光/磨砂
    transparency = Column(String(20), default="")  # 透明度：高透/微透/半透/不透
    curve_id = Column(Integer, ForeignKey("firing_curves.id", ondelete="SET NULL"), nullable=True)  # 关联烧制曲线
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class WorkComment(Base):
    """作品评论"""
    __tablename__ = "work_comments"

    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, ForeignKey("work_comments.id", ondelete="CASCADE"), nullable=True)
    work_id = Column(Integer, ForeignKey("works.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Follow(Base):
    """用户关注"""
    __tablename__ = "follows"
    __table_args__ = (
        UniqueConstraint("follower_id", "followed_id", name="uq_follow_pair"),
        CheckConstraint("follower_id <> followed_id", name="ck_follow_not_self"),
    )

    id = Column(Integer, primary_key=True, index=True)
    follower_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    followed_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RecipeView(Base):
    """配方浏览记录"""
    __tablename__ = "recipe_views"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RecipeIngredient(Base):
    """配方配料表"""
    __tablename__ = "recipe_ingredients"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    recipe_no = Column(String(10), default="")
    name = Column(String(200), nullable=False, default="")  # AES 加密存储
    name_en = Column(String(200), default="")
    name_hash = Column(String(64), default="", index=True)  # SHA-256，用于搜索匹配
    amount = Column(String(500), default="")  # AES 加密存储（密文显著长于明文）
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
    __table_args__ = (
        UniqueConstraint("user_id", "recipe_id", name="uq_like_user_recipe"),
        UniqueConstraint("user_id", "work_id", name="uq_like_user_work"),
        CheckConstraint("(recipe_id IS NULL) <> (work_id IS NULL)", name="ck_like_one_target"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=True)
    work_id = Column(Integer, ForeignKey("works.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    """私信消息"""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    receiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True)
    work_id = Column(Integer, ForeignKey("works.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_read = Column(Boolean, default=False)


class Complaint(Base):
    """User feedback / complaint record."""
    __tablename__ = "complaints"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    images = Column(Text, default="")
    status = Column(String(20), default="open")
    reply = Column(Text, default="")
    admin_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    replied_at = Column(DateTime(timezone=True), nullable=True)
    is_resolved = Column(Boolean, default=False, nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    is_closed = Column(Boolean, default=False, nullable=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ComplaintReply(Base):
    """An administrator reply in a complaint's conversation history."""
    __tablename__ = "complaint_replies"

    id = Column(Integer, primary_key=True, index=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    admin_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class WorkAttributeOption(Base):
    """作品属性可选值（后台配置）"""
    __tablename__ = "work_attribute_options"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(30), nullable=False, index=True)  # type / kiln_type / atmosphere / body_material / surface / transparency
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
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String(200), nullable=False, index=True)        # 中文名
    name_en = Column(String(200), default="")                      # 英文名
    source = Column(String(20), default="")                        # 'local' 或 'overseas'
    source_id = Column(Integer, nullable=True)                     # 外部来源数据ID
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


class RecipeSeger(Base):
    """配方 Seger 公式计算结果"""
    __tablename__ = "recipe_seger"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, unique=True)
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
    """材料相似关系表"""
    __tablename__ = "material_substitutions"
    __table_args__ = (
        UniqueConstraint("source_material_id", "target_material_id", name="uq_material_substitution_pair"),
        CheckConstraint("source_material_id <> target_material_id", name="ck_material_substitution_not_self"),
        CheckConstraint("similarity_score >= 0 AND similarity_score <= 100", name="ck_material_similarity_range"),
        Index("ix_src_mat", "source_material_id"),
        Index("ix_tgt_mat", "target_material_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    source_material_id = Column(Integer, ForeignKey("materials.id", ondelete="CASCADE"), nullable=False, comment="源材料")
    target_material_id = Column(Integer, ForeignKey("materials.id", ondelete="CASCADE"), nullable=False, comment="相似材料")
    similarity_score = Column(Float, default=0.0, comment="成分相似度 0-100")
    status = Column(String(20), nullable=True, comment="历史兼容字段，不再参与业务逻辑")
    note = Column(String(500), default="", comment="相似关系备注")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    source_material = relationship("Material", foreign_keys=[source_material_id])
    target_material = relationship("Material", foreign_keys=[target_material_id])


class UserLevel(Base):
    """用户等级"""
    __tablename__ = "user_levels"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    # 数据库暂沿用 max_free_recipes 列名；应用层统一称为配方额度。
    max_recipes = Column("max_free_recipes", Integer, default=10)
    max_works = Column(Integer, default=50)
    max_views = Column(Integer, default=0, comment="每日可查看配方上限，0=禁止查看")
    description = Column(String(200), default="")
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class UserUsageQuota(Base):
    """用户当日功能剩余额度及累计兑换次数。"""
    __tablename__ = "user_usage_quotas"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    quota_date = Column(Date, nullable=False, index=True)
    # 数据库暂沿用 free_recipe_remaining 列名；应用层不再区分付费/免费配方。
    recipe_remaining = Column("free_recipe_remaining", Integer, nullable=False, default=0)
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
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    view_date = Column(Date, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ToBeFired(Base):
    """待烧（用户计划烧制的配方队列）"""
    __tablename__ = "to_be_fired"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True, index=True)
    note = Column(String(200), default="")  # 备注（如"用XX泥"）
    status = Column(String(20), default="pending")  # pending / firing / done
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Notification(Base):
    """系统通知"""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    from_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    type = Column(String(32), nullable=False)  # comment / follow / like / favorite / complaint_reply
    work_id = Column(Integer, ForeignKey("works.id", ondelete="CASCADE"), nullable=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id", ondelete="CASCADE"), nullable=True)
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

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    materials = Column(Text, default="[]")        # JSON: ["高岭土","长石",...]
    kiln_types = Column(Text, default="[]")       # JSON: ["电窑","气窑"]
    temperatures = Column(Text, default="[]")     # JSON: ["1220℃","1280℃"]
    firing_curve_id = Column(Integer, ForeignKey("firing_curves.id", ondelete="SET NULL"), nullable=True)
    body_material = Column(String(50), default="")
    notification_preferences = Column(Text, default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AppSetting(Base):
    """Application-level key/value settings."""
    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, default="")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RecipeVersion(Base):
    """配方历史版本快照"""
    __tablename__ = "recipe_versions"
    __table_args__ = (
        UniqueConstraint("recipe_id", "version_no", name="uq_recipe_version_no"),
        CheckConstraint("version_no > 0", name="ck_recipe_version_positive"),
    )

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    version_no = Column(Integer, nullable=False)  # 1, 2, 3...
    recipe_data = Column(Text, nullable=False)  # JSON: recipe 表所有字段
    ingredients_data = Column(Text, nullable=False)  # JSON: ingredients 列表
    seger_data = Column(Text, nullable=True)  # JSON: seger 结果
    note = Column(String(200), default="")  # 自动生成的备注
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RedeemCode(Base):
    """兑换码"""
    __tablename__ = "redeem_codes"
    __table_args__ = (
        CheckConstraint("days > 0", name="ck_redeem_days_positive"),
        CheckConstraint("max_uses > 0", name="ck_redeem_max_uses_positive"),
        CheckConstraint("current_uses >= 0 AND current_uses <= max_uses", name="ck_redeem_use_count"),
    )

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(32), unique=True, index=True, nullable=False, comment="兑换码")
    days = Column(Integer, nullable=False, comment="可兑换天数")
    max_uses = Column(Integer, default=1, comment="最大使用次数")
    current_uses = Column(Integer, default=0, comment="已使用次数")
    is_active = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RedeemLog(Base):
    """兑换记录"""
    __tablename__ = "redeem_logs"
    __table_args__ = (
        UniqueConstraint("code_id", "user_id", name="uq_redeem_log_code_user"),
        CheckConstraint("days_added > 0", name="ck_redeem_log_days_positive"),
    )

    id = Column(Integer, primary_key=True, index=True)
    code_id = Column(Integer, ForeignKey("redeem_codes.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    days_added = Column(Integer, nullable=False)
    before_expiry = Column(DateTime(timezone=True), nullable=True, comment="兑换前使用期限")
    after_expiry = Column(DateTime(timezone=True), nullable=True, comment="兑换后使用期限")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
