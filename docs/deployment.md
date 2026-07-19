# 可复现部署

## 首次生产上线顺序

1. 从 `.env.prod.example` 创建 `.env.prod`，填写域名、数据库密码、随机 `AUTH_SECRET`、加密密钥、公开/私有两个对象桶和邮件服务器。生产环境不再允许 `debug` 验证码通道。
2. 在仓库外创建两个仅部署用户可读的文件（Linux 建议 `chmod 600`）：`SMTP_PASSWORD_SECRET_FILE` 只写 SMTP 密码；`INITIAL_ADMIN_PASSWORD_SECRET_FILE` 只写首次管理员密码，且至少 12 位。
3. 在云厂商创建公开图片桶和私有附件桶，启用版本控制、生命周期和异地复制；然后校验配置并初始化空库：

   ```bash
   docker compose --env-file .env.prod config
   docker compose --env-file .env.prod up --build migrate
   ```

4. 创建一次性管理员。重复执行会轮换密码并撤销旧令牌：

   ```bash
   docker compose --env-file .env.prod --profile tools run --rm bootstrap-admin
   ```

5. 启动应用和 MySQL 备份：

   ```bash
   docker compose --env-file .env.prod up -d --build
   docker compose --env-file .env.prod --profile backups up -d mysql-backup
   ```

6. 验证健康检查、管理员登录、邮件验证码、注册、公开图片上传和投诉附件。投诉附件保存在 `S3_PRIVATE_BUCKET`，只通过短时签名地址读取；不得给该桶配置匿名访问。

MySQL 备份必须再复制到异机或云存储，同机 Docker volume 不算灾备。对象存储使用云厂商版本控制、生命周期和跨区域复制保护，不再在本机运行 MinIO 或对象备份容器。

## 固定运行时

- 后端：Python 3.12.13
- 前端：Node.js 24.17.0 LTS
- 数据库：MySQL 8.4.10 LTS
- 反向代理：Nginx 1.28.0
- 缓存：Redis 7.4.3
- 存储：云厂商 S3 兼容 OSS/COS/S3

## 小内存主机

默认 Compose 针对初期的 2 vCPU / 2 GiB 单机部署，为 MySQL 挂载
`deploy/mysql-low-memory.cnf`，将容器限制为 640 MiB，并限制 InnoDB 缓冲池、
连接数、临时表和表缓存。该配置适合低并发起步，不适合长期承载大量并发查询。

2 GiB 主机仍应配置至少 2 GiB swap。默认 Compose 已使用云对象存储，
不再启动同机 MinIO；Redis、API 和两个 Nginx 容器也采用低内存上限。
当数据库工作集或并发增长时，应升级主机或迁移到云数据库，再同步提高
`innodb_buffer_pool_size`、`max_connections` 和 Compose 的 `db.mem_limit`。

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

生产环境使用云厂商 OSS/COS/S3，不在应用服务器运行 MinIO。部署前手工或通过
IaC 创建公开图片桶和私有附件桶。公开桶只能读取具体对象，下载策略不得包含
ListBucket/目录枚举权限；私有桶禁止匿名访问，只通过短时签名地址读取。

配置要求：

- 把 `S3_ENDPOINT_URL` 换成厂商的 S3 兼容地址；AWS S3 可留空。
- 把 `S3_PUBLIC_BASE_URL` 设置为 HTTPS CDN/对象域名。
- 给访问密钥只授予目标 bucket 的读写权限。
- 确认跨域、生命周期、版本控制和跨区域复制策略。

旧 `uploads/` 文件迁移到对象存储后，需要把数据库里的旧 `/uploads/...` URL 批量转换为对象存储 URL；此操作应在正式数据迁移阶段执行。

## 日志与健康检查

- 容器日志写 stdout/stderr，由云日志服务采集；`LOG_TO_FILE=0`。
- 本地开发默认按天滚动 `logs/server.log`，保留 14 天。
- `/health/live` 只检查进程。
- `/health/ready` 同时检查数据库和对象存储；反向代理只在 ready 成功后接流量。

## 发布与回滚

发布前顺序：数据库快照 → 构建不可变镜像 → 执行迁移 → readiness 通过 → 切换流量。应用镜像可以回滚；发生不可逆数据库迁移时必须从快照恢复，不能只回滚镜像。
