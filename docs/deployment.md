# 可复现部署

## 固定运行时

- 后端：Python 3.12.13
- 前端：Node.js 24.17.0 LTS
- 数据库：MySQL 8.4.10 LTS
- 反向代理：Nginx 1.28.0
- 自托管对象存储：MinIO `RELEASE.2025-09-07T16-13-09Z`

本地直接运行时应使用 `.python-version`、`runtime.txt` 和前端 `.nvmrc` 中的版本。容器部署使用相同版本。

## 首次部署

1. 复制安全配置模板，实际文件不要提交 Git：

   ```bash
   cp .env.prod.example .env.prod
   ```

2. 设置域名、数据库密码、`AUTH_SECRET`、两类数据加密密钥和 S3 密钥。数据库密码包含特殊字符时，`DATABASE_URL` 中必须 URL 编码。

3. 先检查最终 Compose 配置，再启动：

   ```bash
   docker compose --env-file .env.prod config
   docker compose --env-file .env.prod up -d --build
   ```

4. 验证：

   ```bash
   curl -fsS http://127.0.0.1:8080/health/live
   curl -fsS http://127.0.0.1:8080/health/ready
   ```

默认访问入口为 `http://服务器:8080/web/`。正式域名应在云负载均衡或外层网关终止 HTTPS，再转发到本项目代理；不要把 MySQL、MinIO API 或后端容器端口直接暴露公网。

## 数据库迁移

Compose 使用一次性 `migrate` 服务执行 `alembic upgrade head` 和幂等预置数据；
`api` 等待该 Job 成功后才启动。API 容器入口不再执行迁移或初始化，扩容 worker
和滚动发布不会重复运行数据库变更。

现有数据库第一次接入时也直接执行：

```bash
alembic upgrade head
alembic current
```

每日等级与额度维护由外部调度器运行：

```bash
docker compose --profile jobs run --rm maintenance
```

任务使用 MySQL `GET_LOCK`，即使调度器重试或多实例同时触发也只会执行一次。

迁移前必须做数据库快照。`0002_remove_legacy_features` 删除了付费和旧材料数据，无法通过 downgrade 恢复。

## 对象存储

Compose 默认提供自托管 MinIO，并创建仅对象下载、认证写的 `yunyao-uploads`
bucket；下载策略不得包含 ListBucket/目录枚举权限。上传 API 只接受登录用户，
浏览器通过 `/media/<bucket>/...` 读取图片。上线前应按业务保留期配置未引用对象
清理和生命周期规则。

使用云厂商 OSS/COS/S3 时：

- 把 `S3_ENDPOINT_URL` 换成厂商的 S3 兼容地址；AWS S3 可留空。
- 把 `S3_PUBLIC_BASE_URL` 设置为 HTTPS CDN/对象域名。
- 给访问密钥只授予目标 bucket 的读写权限。
- 确认跨域、生命周期、版本控制和备份策略。

旧 `uploads/` 文件迁移到对象存储后，需要把数据库里的旧 `/uploads/...` URL 批量转换为对象存储 URL；此操作应在正式数据迁移阶段执行。

## 日志与健康检查

- 容器日志写 stdout/stderr，由云日志服务采集；`LOG_TO_FILE=0`。
- 本地开发默认按天滚动 `logs/server.log`，保留 14 天。
- `/health/live` 只检查进程。
- `/health/ready` 同时检查数据库和对象存储；反向代理只在 ready 成功后接流量。

## 发布与回滚

发布前顺序：数据库快照 → 构建不可变镜像 → 执行迁移 → readiness 通过 → 切换流量。应用镜像可以回滚；发生不可逆数据库迁移时必须从快照恢复，不能只回滚镜像。
