# 云窑系统 API 接口文档

> 后端地址由部署环境的 `API_BASE_URL` 决定，本地默认通过前端开发代理访问。  
> 更新日期: 2026-07-13  
> 应用: Yunyao App API v0.2.0

---

## 目录

1. [认证相关](#1-认证相关-auth)
2. [用户模块](#2-用户模块-users)
3. [配方模块](#3-配方模块-recipes)
4. [作品模块](#4-作品模块-works)
5. [兑换码](#5-兑换码)
6. [配料表](#6-配料表-recipe-ingredients)
7. [材料库存/相似品](#7-材料库存相似品-materials)
8. [烧制曲线](#8-烧制曲线-curves)
9. [社交/消息](#9-社交消息-social)
10. [通知/投诉](#10-通知投诉)
11. [评论](#11-评论-work-comments)
12. [上传/OCR](#12-上传ocr)
13. [设置](#13-设置-settings)
14. [附属资料（术语/原材料/测温锥）](#14-附属资料)
15. [后台管理](#15-后台管理-admin)
16. [通用/杂项](#16-通用杂项)

---

## 1. 认证相关 (auth)

**前缀**: `/auth` | **公开接口**: 全部公开（无需登录）

### POST `/auth/send-code`
发送验证码（邮箱或手机）
- **请求体**: `{ email?: string, phone?: string }`
- **响应**: `{ message, target, expires_in, channel, debug_code? }`（`debug_code` 仅开发环境允许）

### GET `/auth/captcha`
获取图形验证码
- **响应**: `{ captcha_id, captcha_image (base64 PNG) }`

### GET `/auth/verify`
校验当前 Token 是否有效
- **请求头**: `Authorization: Bearer <token>`
- **响应**: `{ valid, user_id, username, nickname, role }`

### POST `/auth/find-user`
找回账号（验证用户名+邮箱）
- **请求体**: `{ username, email }`
- **响应**: `{ found: bool, message }`

### POST `/auth/verify-code`
验证验证码（不消费，用于找回密码流程）
- **请求体**: `{ email?: string, phone?: string, code }`
- **响应**: `{ valid, message }`

### POST `/auth/register`
- **请求体**: `{ email?, phone?, username, verification_code, captcha_id, captcha_code, password, confirm_password }`
- **响应**: `{ access_token, token_type, user_id, username, nickname, role, expires_at }`

### POST `/auth/login`
- **请求体**: `{ email?, phone?, password?, verification_code?, username? }`
- **支持登录方式**: 验证码登录 / 邮箱或手机号密码登录 / 用户名密码登录
- **响应**: `{ access_token, token_type, user_id, username, nickname, role, expires_at }`

### PUT `/auth/nickname`
更新昵称
- **查询参数**: `user_id`
- **请求体**: `{ nickname }`

### POST `/auth/reset-password`
重置密码
- **请求体**: `{ email, verification_code, password, confirm_password }`

---

## 2. 用户模块 (users)

**前缀**: `/users` | **需要登录**: ✅（publish-status / view-status 公开）

### GET `/users/me`
当前登录用户完整信息（含敏感字段）
- **响应**: `{ id, username, nickname, avatar, bio, gender, birthday, location, phone(解密), email(解密), level_id, level_name, expires_at }`

### GET `/users/profile?user_id=`
他人公开个人信息+统计
- **响应**: `{ id, username, nickname, avatar, bio, gender, birthday, location, level_id, level_name, following_count, follower_count, recipe_count, work_count, favorite_count, collected_count, curve_count, to_fire_count, expires_at }`

### PUT `/users/profile`
更新个人信息
- **请求体**: `{ nickname?, avatar?, bio?, phone?, email?, gender?, birthday?, location? }`
- 手机/邮箱加密存储，去重校验

### GET `/users/publish-status?user_id=`
发布资格状态（不含 user_id 返回默认等级配额）
- **响应**: `{ ok, can_publish_recipe, can_publish_work, recipe_remaining, work_remaining, recipe_limit, recipe_count, work_limit, work_count, is_guest }`

### GET `/users/view-status?user_id=&recipe_id=`
今日配方查看额度
- **响应**: `{ can_view, today_views, max_views, remaining, reason }` 或 `{ can_view, is_owner }`

### 待烧 (To Be Fired)
| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/users/to-be-fired` | 待烧列表 | `user_id, page, page_size` |
| POST | `/users/to-be-fired` | 添加待烧 | `user_id` + body: `{ recipe_id, note? }` |
| PUT | `/users/to-be-fired/{item_id}` | 更新状态/备注 | `user_id` + body: `{ status?, note? }` |
| DELETE | `/users/to-be-fired/{item_id}` | 移除待烧 | `user_id` |

---

## 3. 配方模块 (recipes)

**前缀**: `/recipes` | **公开 GET 列表**: 是 | **创建/修改/删除**: 需登录

### 列表与搜索
| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/recipes` | 配方列表（分页+筛选） | `page, page_size, type, category, atmosphere, body_material, keyword, author_id, material, has_work, surface, transparency, color_range, temperature, kiln_type, has_images` |
| GET | `/recipes/search` | 搜索配方+作品 | `keyword, category, atmosphere, body_material, kiln_type, surface, transparency, color_range, temperature, has_images, author_id, page, page_size` |
| GET | `/recipes/search/config` | 搜索筛选项配置 | 无参数 |
| GET | `/recipes/count` | 配方数量统计 | 同筛选参数 |
| GET | `/recipes/feed/following` | 关注用户配方动态 | `user_id, page, page_size` |
| GET | `/recipes/mine` | 我的配方 | `user_id` |
| GET | `/recipes/favorites` | 用户收藏列表（配方+作品） | `user_id, page, page_size` |

### 单个配方操作
| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/recipes/{recipe_id}` | 配方详情 | `user_id?` |
| GET | `/recipes/by-no/{recipe_no}` | 按编号查配方 | - |
| POST | `/recipes/` | 创建配方 | `user_id` + RecipeCreate body |
| PUT | `/recipes/{recipe_id}` | 更新配方 | `user_id` + RecipeUpdate body |
| DELETE | `/recipes/{recipe_id}` | 删除配方 | `user_id` |
| POST | `/recipes/init-sequence` | 初始化编号计数器 | - |

### 交互操作
| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| POST | `/recipes/{recipe_id}/favorite` | 切换收藏 | `user_id` |
| POST | `/recipes/{recipe_id}/like` | 切换点赞 | `user_id` |
| POST | `/recipes/{recipe_id}/view` | 记录浏览（扣额度） | `user_id` |

### 评价
| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| POST | `/recipes/review` | 创建评价/回复 | `user_id` + ReviewCreate body |
| GET | `/recipes/{recipe_id}/reviews` | 评价列表（含回复） | - |

### Seger 公式 & 版本
| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/recipes/{recipe_id}/seger` | Seger 公式计算结果 | - |
| GET | `/recipes/{recipe_id}/versions` | 版本历史 | - |
| GET | `/recipes/{recipe_id}/versions/{version_id}` | 版本详情 | - |
| POST | `/recipes/{recipe_id}/versions/{version_id}/restore` | 恢复版本 | `user_id` |

### RecipeCreate 请求体
```json
{ "title": "必填", "type": "recipe", "cover": "", "images": "[]", "describe": "",
  "category": "", "temperature": "", "atmosphere": "", "kiln_type": "",
  "body_material": "", "surface": "", "transparency": "", "visibility": "private",
  "work_id": 0, "forked_from": null, "glaze_colors": null }
```

### RecipeOut 响应字段
`id, user_id, title, recipe_no, type, cover, images, describe, category, temperature, atmosphere, kiln_type, body_material, surface, transparency, visibility, likes, created_at, updated_at, is_favorited, forked_from, source, source_id, author_name, avatar, rating_avg, favorite_count, works_count, is_liked, ingredient_statuses, glaze_colors`

---

## 4. 作品模块 (works)

**前缀**: `/works` | **公开 GET 列表**: 是 | **创建/修改**: 需登录

### 列表与搜索
| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/works` | 作品列表（分页+高级筛选） | `page, page_size, q, user_id, recipe_id, category, atmosphere, body_material, kiln_type, temperature, surface, transparency, color_range, has_recipe, current_user_id` |
| GET | `/works/search/config` | 搜索配置选项 | - |
| GET | `/works/count` | 作品数量统计 | 同筛选参数 |
| GET | `/works/feed/following` | 关注用户作品动态 | `user_id, page, page_size` |
| GET | `/works/mine` | 我的作品列表 | `user_id` |

### 单个作品操作
| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/works/{work_id}` | 作品详情 | `current_user_id?` |
| POST | `/works/` | 发布作品 | body: `{ image(必填), user_id(必填), description?, recipe_id?, category?, atmosphere?, body_material?, kiln_type?, temperature?, surface?, transparency?, images?, glaze_colors?, curve_id? }` |
| PUT | `/works/{work_id}` | 更新作品 | body: 同上 |
| POST | `/works/{work_id}/favorite` | 收藏/取消 | body: `{ user_id }` |
| POST | `/works/{work_id}/like` | 点赞/取消 | `user_id` |
| POST | `/works/{work_id}/link_recipe` | 关联配方 | body: `{ user_id, recipe_id }` |

### 作品详情响应字段
`id, user_id, nickname, avatar, recipe_id, recipe_title, recipe_cover, image, images, description, category, atmosphere, body_material, kiln_type, temperature, created_at, favorite_count, is_favorited, is_liked, likes, glaze_colors, surface, transparency, curve_id, curve_name, curve_data`

---

## 5. 兑换码

**前缀**: `/redeem`
| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| POST | `/redeem/admin/generate` | 生成兑换码（管理） | `token` + body: `{ count, days, max_uses }` |
| GET | `/redeem/admin/codes` | 兑换码列表（管理） | `token, page, page_size` |
| POST | `/redeem/use` | 使用兑换码 | request 鉴权 + body: `{ code }` |

---

## 6. 配料表 (recipe-ingredients)

**前缀**: `/recipe-ingredients`

| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/recipe-ingredients/{recipe_id}` | 获取配料表（解密） | 按配方可见范围校验 |
| POST | `/recipe-ingredients/{recipe_id}` | 全量替换配料 | 自动触发 Seger 重算 |

**请求体** (POST): `[{ name, name_en?, amount, unit, note?, is_additional?, sort_order? }]`

---

## 7. 材料库存/相似品 (materials)

**前缀**: `/materials`

### 材料 CRUD
| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/materials` | 材料列表 | `user_id, status?, category?, search?, page, page_size` |
| GET | `/materials/categories` | 材料分类统计 | `user_id` |
| POST | `/materials` | 添加材料 | `user_id` + body: `{ name, status?, category?, from_recipe_id? }` |
| PUT | `/materials/{item_id}` | 更新材料 | `user_id` + body |
| DELETE | `/materials/{item_id}` | 删除材料 | `user_id` |
| POST | `/materials/batch_delete` | 批量删除 | `user_id` + body: `{ ids: [int] }` |

### 购物清单
| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| POST | `/materials/wishlist` | 加入购物清单 | `user_id` + body: `{ name, status?, category?, from_recipe_id? }` |
| POST | `/materials/wishlist/batch` | 批量加入 | `user_id` + body: `{ names: [str], from_recipe_id? }` |
| POST | `/materials/wishlist/move/{item_id}` | 移入购物清单 | `user_id` |
| POST | `/materials/move_to_wishlist/{item_id}` | 移入购物清单 | `user_id` |
| POST | `/materials/wishlist/reorder` | 排序 | `user_id` + body: `{ ids: [int] }` |

### 材料相似品
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/materials/{material_id}/substitutions` | 获取相似品（含全部氧化物，只读） |

相似度按全部氧化物实际含量（包含 LOI）计算：
`100 × (1 - Σ|Aᵢ-Bᵢ| / Σ(Aᵢ+Bᵢ))`。仅当全部含量逐项一致时返回 `100.00%`；缺失值按 `0` 参与计算。

---

## 8. 烧制曲线 (curves)

**前缀**: `/curves` | **GET 列表公开，其余需登录**

| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/curves` 或 `/curves/` | 曲线列表 | `user_id` |
| GET | `/curves/{curve_id}` | 曲线详情 | `user_id` |
| POST | `/curves` 或 `/curves/` | 创建曲线 | `user_id` + body: `{ name(必填), type?, target_temp?, segments?, description?, sort_order? }` |
| PUT | `/curves/{curve_id}` | 更新曲线 | `user_id` + 可选 body 字段 |
| POST | `/curves/{curve_id}/copy` | 复制曲线 | `user_id` |
| DELETE | `/curves/{curve_id}` | 删除曲线 | `user_id` |

---

## 9. 社交/消息 (social)

**前缀**: `/social`

### 关注
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/social/follow/{target_id}` | 关注 | `user_id` |
| DELETE | `/social/follow/{target_id}` | 取关 | `user_id` |
| GET | `/social/following` | 关注列表 | `user_id` |
| GET | `/social/followers` | 粉丝列表 | `user_id` |
| GET | `/social/status` | 关注状态 | `target_id, user_id` |

### 私信
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/social/conversations` | 会话列表 | `user_id` |
| GET | `/social/messages/{other_user_id}` | 历史消息 | `user_id, page, page_size` |
| POST | `/social/messages/{other_user_id}` | 发送消息 | `user_id` + body: `{ content, recipe_id? }` |
| POST | `/social/messages/{message_id}/read` | 标记已读 | `user_id` |
| GET | `/social/unread-count` | 未读消息数 | `user_id` |

---

## 10. 通知/投诉

### 通知 (notifications) — 前缀 `/notifications`
| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/notifications/` | 通知列表 | `user_id, page, page_size` |
| GET | `/notifications/unread_count` | 未读数量 | `user_id` |
| POST | `/notifications/mark_read` | 标记已读 | body: `{ user_id, notification_id? }` |

**通知类型**: `comment / follow / like / favorite`

### 投诉建议 (complaints) — 前缀 `/complaints`
| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/complaints` | 当前用户投诉列表（含多轮答复与状态） | `user_id` |
| POST | `/complaints` | 提交投诉 | body: `{ user_id, content, images? }` |
| PUT | `/complaints/{complaint_id}/resolved` | 提问人标记已解决/未解决 | body: `{ resolved }` |
| POST | `/complaints/{complaint_id}/reply` | 管理员回复（兼容接口） | body: `{ reply }` |
| GET | `/admin/complaints` | 后台投诉列表与筛选 | `q, answered, resolved, closed, date_from, date_to, page, page_size` |
| GET | `/admin/complaints/{complaint_id}` | 后台投诉详情 | - |
| POST | `/admin/complaints/{complaint_id}/replies` | 后台追加答复 | body: `{ content }` |
| PUT | `/admin/complaints/{complaint_id}/closed` | 后台关闭/重新打开 | body: `{ closed }` |

---

## 11. 评论 (work-comments)

**前缀**: `/works` (与作品模块共用前缀，但路由不冲突)

| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/works/{work_id}/comments` | 评论列表（含嵌套回复） | - |
| POST | `/works/{work_id}/comments` | 发表评论/回复 | body: `{ user_id, content, parent_id? }` |

---

## 12. 上传/OCR

### 上传 (upload) — 前缀 `/upload`
| 方法 | 路径 | 说明 | 限制 |
|------|------|------|------|
| POST | `/upload/image` | 上传图片 | 需 Bearer Token；JPG/PNG/GIF/WebP, ≤10MB, 魔数校验 |

**响应**: `{ url, filename }`

### OCR (ocr) — 前缀 `/ocr`
| 方法 | 路径 | 说明 | 限制 |
|------|------|------|------|
| POST | `/ocr/image` | 图片文字识别（百度OCR） | JPG/PNG/BMP, ≤3MB, 15-4096px |

**响应**: `{ text, lines: [str], count }`

---

## 13. 设置 (settings)

**前缀**: `/settings`

| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/settings` | 获取用户默认设置 | `user_id` |
| PUT | `/settings` | 更新默认设置 | `user_id` + body: `{ materials?, kiln_types?, temperatures?, firing_curve_id?, body_material? }` |
| GET | `/settings/curves` | 所有烧制曲线（选择用） | 无需登录 |

---

## 14. 附属资料

### 术语表 (glossary) — 前缀 `/glossary`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/glossary` | 术语列表 | `q?, page_size` |
| GET | `/glossary/{term_id}` | 术语详情 |
| POST | `/glossary` | 创建术语 |
| PUT | `/glossary/{term_id}` | 更新术语 |
| DELETE | `/glossary/{term_id}` | 删除术语 |

### 统一原材料目录 — 前缀 `/materials/catalog`
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/materials/catalog` | 合并后的原材料列表（含氧化物） | `q, page, page_size` |
| GET | `/materials/catalog/{material_id}` | 原材料详情 |

### 测温锥 (temperature-cones) — 前缀 `/temperature-cones`
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/temperature-cones` | 温度对照表 | `q?, page_size` |

**响应字段**: `cone_no, temp_60c, temp_108f, temp_150c, temp_270f`

---

## 15. 后台管理 (admin)

**前缀**: `/admin` | **全部需管理认证** (POST `/admin/login` 除外)

### 登录 & 统计
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/admin/login` | 管理员登录 | body: `{ username, password }` → `{ token, user_id, nickname, role }` |
| GET | `/admin/stats` | 全局统计 | `user_count, recipe_count, work_count, muted_count` |

### 用户管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/users` | 用户列表 | `q, page, page_size` |
| GET | `/admin/users/{user_id}` | 用户详情 |
| PUT | `/admin/users/{user_id}` | 更新用户 | body: `{ level_id?, is_muted?, is_admin?, expires_at? }` |

### 等级管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/levels` | 等级列表（含用户数） |
| POST | `/admin/levels` | 创建等级 | body: `{ name, max_recipes?, max_works?, max_views?, description?, sort_order? }` |
| PUT | `/admin/levels/{level_id}` | 编辑等级 |
| DELETE | `/admin/levels/{level_id}` | 删除等级（系统默认不可删） |

### 作品属性 & 搜索配置
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/work-attributes` | 属性选项（分组） |
| GET | `/admin/public/work-attributes` | **公开** 属性选项（发布页下拉建议，仍允许自由输入） |
| POST | `/admin/work-attributes` | 创建选项 |
| PUT | `/admin/work-attributes/{opt_id}` | 编辑选项 |
| DELETE | `/admin/work-attributes/{opt_id}` | 删除选项 |
| GET | `/admin/work-search-settings` | 温度/颜色范围配置 |
| PUT | `/admin/work-search-settings` | 更新温度/颜色范围 |

### 系统配置
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/verification-settings` | 验证码配置（脱敏） |
| PUT | `/admin/verification-settings` | 更新验证码配置 |

### 材料管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/materials` | 全部原材料（本地+海外） | 通过 Depends(verify_admin) 鉴权 |

---

## 16. 通用/杂项

### 在 main.py 中定义

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/` | 健康检查 → `{ status: "running" }` | 无 |
| GET | `/admin-panel` | 后台管理页面 | 无 |
| GET | `/admin` 或 `/admin/` | 同 admin-panel | 无 |
遗留的 `GET /api/favorites` 已删除。收藏列表使用已鉴权的
`GET /recipes/favorites`；作品收藏应通过正式 Router 增补，不得在
`main.py` 中增加接收任意 `user_id` 的旁路接口。

### 静态挂载
| 路径 | 说明 |
|------|------|
| `/web/**` | H5 前端构建产物 |
| `/static/**` | 后台管理页面 |
| `/uploads/**` | 上传图片 |

---

## 认证方式

- **普通用户**: JWT Token → `Authorization: Bearer <token>` 请求头
- **后台管理**: 登录后返回 JWT，通过 `Authorization: Bearer <token>` 请求头传递
- **公开接口**: 不需要认证（公开 GET 列表、GET 单条详情及认证相关接口）；上传和 OCR 均需登录

## 公共中间件

| 中间件 | 说明 |
|--------|------|
| CORS | 支持跨域（开发环境允许所有来源） |
| GZip | 压缩 ≥1KB 的响应 |
| 限流 | 60次/60秒（统一限制，不显示数字） |
| IP白名单 | 后台管理路径限制访问IP |
| Token校验 | 非公开接口自动验证 JWT |
| Page Size 上限 | 列表接口单页最大值限制 |

## 响应格式

- 成功: 标准 JSON 对象或数组
- 错误: `{ "detail": "错误信息" }`
- 列表接口: 通常返回 `{ items/data: [...], total, page, page_size/has_more }`
- 状态码: 200(成功), 400(参数错误), 401(未登录), 403(无权限), 404(不存在), 500(服务器错误)
