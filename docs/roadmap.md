# 云窑上线整理清单

更新时间：2026-07-13

## 已完成

- [x] 删除钱包、充值、购买和付费配方代码、接口、表及字段
- [x] 合并旧材料表到 `materials`，删除 `glazy_materials` / `ceramic_materials`
- [x] 删除前端一键复制配方功能
- [x] 删除微信登录、openid、微信配置和前端微信工程文件
- [x] 关闭模拟登录、匿名上传和用户 ID 越权入口
- [x] 管理认证改为 Bearer JWT，建立生产配置强校验
- [x] 固定 Python/Node/MySQL 版本并提供 Docker Compose
- [x] 建立 Alembic 迁移，当前测试库位于 `0003_remove_wechat_identity (head)`
- [x] 增加 S3 兼容对象存储、本地存储适配、滚动日志和健康检查
- [x] 增加前后端容器、Nginx 反向代理及部署文档

## P0：正式上线前必须完成

- [ ] 轮换曾写入旧 `.env.prod` 的数据库密码；即使尚未生产使用也不复用
- [ ] 上线前轮换当前测试环境的百度 OCR API Key/Secret，并改由云平台 Secret 注入
- [ ] 确定最终云数据库和对象存储厂商，创建最小权限账号和 bucket
- [ ] 把现有 `uploads/` 文件上传到对象存储，并迁移数据库中的旧 `/uploads/...` URL
- [ ] 生成并异地备份 `AUTH_SECRET`、个人数据密钥、配方密钥；确认旧密文可解密
- [ ] 把验证码通道从 `debug` 切换为正式邮件或短信，并做发送限额/失败告警
- [ ] 配置正式域名、TLS 证书、HTTPS CORS、CDN/对象存储跨域规则
- [ ] 在安装 Docker 的 Linux/CI 环境执行完整 `docker compose build` 和首次启动演练
- [ ] 做数据库备份与恢复演练，验证 Alembic、对象文件和数据库快照能够同步回滚
- [ ] 校验云负载均衡后的真实客户端 IP，再启用后台管理 IP 白名单

> 本机当前未安装 Docker，因此本轮已验证源码、迁移、前端构建和运行中健康检查，但无法在本机实际构建镜像。

## 阶段 3：接口契约和断链导航

已确认问题：

- [x] 删除旧首页指向未注册 `/pages/search/search` 的断链
- [x] 把详情页错误的 `uni.switchTab` 改为自定义 TabLayout 跳转
- [x] 用户主页统一到 `/pages/user/user?user_id=`
- [x] 删除重复 `/uploads` 代理，移除源码中的局域网 HMR/API 地址

需要系统扫描：

- [ ] 从 FastAPI OpenAPI 与前端请求字面量生成接口对照表，核对方法、参数、响应和鉴权
- [ ] 全量检查 `navigateTo`、`redirectTo`、`reLaunch`、`switchTab` 与 `pages.json`
- [ ] 检查详情、编辑、草稿、通知、关注、收藏、材料、曲线和兑换码的完整用户路径
- [ ] 为反向代理补充接口路径自动校验，避免新增后端路由未进入 Nginx

## 阶段 4：功能保留与删除

明确删除：

- [x] 钱包、充值、购买、付费配方、配方复制
- [x] 旧 Glazy/ceramic 材料接口和表

建议保留：

- [ ] 收藏、点赞、关注、评论、通知、投诉建议
- [ ] 统一材料库、烧制曲线、作品和配方管理

需要确认：

- [ ] “兑换时限”、用户等级和每日额度是否仍符合无收费定位；若只是运营赠送，应统一文案，若不再需要则整组删除
- [x] 删除被新版 Tab 组件替代的 `pages/index`、`pages/mine`、`pages/glossary`
- [x] 删除无入口的旧 `pages/favorites` 页面，收藏功能继续保留在新版“我的”Tab
- [x] 删除包含硬编码端口/密码且已被统一入口替代的旧启动和离线安装脚本

## 阶段 5：代码、依赖、测试和 CI

优先拆分的大文件：

- 前端 `recipe.vue` 约 95 KB、`work.vue` 约 65 KB
- 前端两个发布页各约 53–54 KB，`works-list.vue` 约 37 KB
- 后端 `routes/recipes.py` 约 47 KB、`routes/works.py` 约 28 KB、`models.py` 约 25 KB

治理项：

- [ ] 把详情页拆为信息、配料、评论、作品关联等组件和 composables
- [ ] 把发布页拆为表单模型、图片上传、草稿、属性选择和提交服务
- [ ] 把后端路由拆成查询、命令、序列化和领域服务，缩小 `main.py`
- [x] 删除 `scripts/test_seger.py` 的硬编码 root 数据库连接，统一使用 `DATABASE_URL`
- [ ] 清理仓库内 `.venv`、`Python314Libsite-packages`、wheels 和旧离线安装逻辑
- [ ] 后端建立 pytest：鉴权、越权、上传、配方隐私、迁移和健康检查
- [ ] 前端建立 API/导航静态测试和关键 composable 单元测试
- [ ] CI 执行 Python AST/pytest/Alembic 检查、前端 `npm ci && npm run build:h5`、依赖审计和 Docker build
- [ ] 增加镜像漏洞扫描、Secret 扫描和生产部署前人工审批
