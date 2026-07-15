# 云窑生产上线与恢复手册

## 上线硬门槛

1. 前端 `frontend-ci` 与后端 `backend-ci` 必须是分支保护的 required checks。
2. 生产镜像变量使用不可变 digest，例如 `API_IMAGE=registry/yunyao-api@sha256:...`，禁止 `latest`。
3. 启动 `backups` profile，并把 `backup_data` 卷复制到异机或云端加密存储；同机副本不算灾备。
4. Prometheus 抓取 API 容器的 `/metrics`，告警至少覆盖：5xx、P95/P99 延迟、慢 SQL、验证码失败率、上传失败率、实例存活和备份超时。
5. 配置 Sentry DSN 或兼容服务，发布版本号随镜像注入。

## 首次迁移 uploads（禁止直接删除源目录）

先生成 85 个文件的逐文件 SHA-256 清单：

```sh
python scripts/migrate_uploads_to_s3.py --manifest uploads-migration-manifest.ndjson
```

核对文件数和总字节数后才执行上传：

```sh
python scripts/migrate_uploads_to_s3.py --execute --manifest uploads-migration-manifest.executed.ndjson
```

脚本会逐个校验对象大小和 SHA-256 元数据，且永不删除本地文件。应用切换对象存储后至少观察 7 天，抽检数据库 URL 与对象可读性；只有另行人工审批后才能归档本地 `uploads`。

## 自动备份与恢复演练

```sh
docker compose --profile backups up -d mysql-backup object-backup
```

默认每日备份、保留 14 天。用 `BACKUP_INTERVAL_SECONDS` 和 `BACKUP_RETENTION_DAYS` 调整。每周检查新备份时间、大小、校验文件，并把备份卷异地复制。

数据库恢复只能写入以 `_restore_drill` 结尾的临时库：

```sh
docker compose --profile backups run --rm \
  -e CONFIRM_RESTORE_DRILL=yes \
  -e RESTORE_DATABASE=yunyao_restore_drill \
  -e BACKUP_FILE=/backups/mysql/yunyao-TIMESTAMP.sql.gz \
  --entrypoint /opt/backup/mysql-restore-drill.sh mysql-backup
```

对象恢复只能写入以 `-restore-drill` 结尾的临时桶：

```sh
docker compose --profile backups run --rm \
  -e CONFIRM_RESTORE_DRILL=yes \
  -e RESTORE_BUCKET=yunyao-uploads-restore-drill \
  -e BACKUP_PATH=/backups/objects/yunyao-uploads-TIMESTAMP \
  --entrypoint /opt/backup/object-restore-drill.sh object-backup
```

每月至少演练一次，并记录 RPO（最近可恢复点）与 RTO（恢复耗时）。

## 数据库迁移与回滚

- 只允许向前兼容的 expand/contract 迁移：先加字段/表，再发布兼容代码，最后在后续版本删除旧结构。
- 发布前执行 `alembic upgrade head && alembic check`；CI 会实际执行最新迁移的 downgrade/upgrade。
- 灰度期间禁止破坏旧实例仍会读取的字段。
- 失败时优先回滚应用镜像；只有迁移的 `downgrade()` 已在恢复演练库验证且无数据丢失时才执行 `alembic downgrade -1`。
- 破坏性迁移只能通过备份恢复回滚，发布前必须单独审批。

## 10% 灰度发布

1. 先执行迁移任务，确认稳定实例 readiness 正常。
2. 设置 `CANARY_API_IMAGE` 为新镜像 digest，执行：

   ```sh
   docker compose -f docker-compose.yml -f docker-compose.canary.yml up -d api-canary proxy
   ```

3. `nginx.canary.conf` 按 9:1 分流。观察至少 30 分钟，对比稳定/灰度版本的 5xx、延迟、验证码和上传指标。
4. 用真实双实例路径验证：A 实例生成验证码、B 实例消费；并发触发限流；并发消费配额与同一兑换码；同时启动两次 maintenance，确认只有一个拿到数据库锁。
5. 异常时移除 canary override 并重建 proxy；正常时逐步改权重为 50%、100%，最后把稳定镜像更新到同一 digest。

## 双实例一致性依据

- 验证码/图形验证码：Redis TTL 键，Lua 原子消费。
- 限流：Redis 滑动窗口。
- 配额/兑换码：数据库行锁与唯一约束，授权矩阵和并发路径必须在预发布环境复验。
- 定时任务：容器外调度，MySQL `GET_LOCK` 防止重复执行。
