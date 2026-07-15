# 生产安全基线

上线时从 `.env.prod.example` 复制配置到部署平台的 Secret/环境变量中，不要把实际 `.env` 提交到仓库。

## 启动前强制检查

`APP_ENV=production` 时，应用会拒绝以下不安全配置并终止启动：

- 默认、占位或短于 32 位的 `AUTH_SECRET`
- 未显式配置 `DATABASE_URL`
- 开启 `ALLOW_DEV_CORS`
- 空、通配符或非 HTTPS 的 `CORS_ORIGINS`
- 未提供个人数据和配方加密密钥

生产环境还会关闭 `/docs`、`/redoc` 和 `/openapi.json`，并禁止验证码 `debug` 通道。

## 密钥要求

- `AUTH_SECRET`：使用密码学安全随机值，至少 32 位。
- `PERSONAL_DATA_ENCRYPTION_KEY`：Fernet key，用于手机号和邮箱。
- `RECIPE_ENCRYPT_KEY`：高熵口令，用于配方原料加密。
- 也可把现有密钥文件挂载到 `ENCRYPTION_KEY_FILE`，但不得打进镜像或提交 Git。
- 数据库使用独立的最小权限账号，不使用 root。

## 接口约束

- 图片上传和 OCR 必须携带用户 Bearer Token。
- 写接口会同时校验查询参数和 JSON 请求体中的用户 ID，必须与 Token 一致。
- 管理接口只接受 Bearer JWT，不再接受 URL 查询参数令牌或静态 `ADMIN_TOKEN`。
- `/users/profile` 仅本人返回账号字段、有效期和私有统计；查看他人时只返回公开资料。
# Production hardening notes

## Encryption key rotation

Configure `ENCRYPTION_KEYS` as a JSON mapping of key IDs to Fernet keys and set
`ENCRYPTION_ACTIVE_KEY_ID` to the key used for new writes. Keep every old key in
the keyring while migrating. Run `python scripts/rotate_encryption_keys.py`
first (dry run), then rerun with `--apply`. Remove an old key only after the dry
run reports zero values. Versioned ciphertext uses `enc:v1:<key-id>:...`; an
unknown key or failed authentication raises an error and is never returned as
plaintext.

## SMTP secret

`smtp_password` is no longer read from or written to `app_settings`; migration
0007 deletes any legacy row. Inject `SMTP_PASSWORD` from the cloud secret
manager, or mount a secret file and set `SMTP_PASSWORD_FILE`. The administration
API may display a mask but cannot replace the deployment-managed secret.

## Distributed rate limits

Set `REDIS_URL` and restrict `TRUSTED_PROXY_IPS` to the actual reverse-proxy
network. Production fails closed with 503 if Redis is unavailable. Authentication,
OCR, uploads, writes, administration, and reads use separate policies.
