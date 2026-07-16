import os


def _load_dotenv() -> None:
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_dotenv()


APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV in {"production", "prod"}


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _split_int_csv(value: str) -> set[int]:
    result: set[int] = set()
    for item in _split_csv(value):
        try:
            result.add(int(item))
        except ValueError:
            continue
    return result


_DATABASE_URL_FROM_ENV = os.getenv("DATABASE_URL", "").strip()
if not _DATABASE_URL_FROM_ENV:
    raise RuntimeError("缺少 DATABASE_URL，请通过 .env 或运行环境配置")
DATABASE_URL = _DATABASE_URL_FROM_ENV

AUTH_SECRET = os.getenv("AUTH_SECRET", "").strip()
if not AUTH_SECRET:
    raise RuntimeError("缺少 AUTH_SECRET，请通过 .env 或运行环境配置")
ACCESS_TOKEN_EXPIRE_SECONDS = int(os.getenv("ACCESS_TOKEN_EXPIRE_SECONDS", "604800"))

ADMIN_USER_IDS = _split_int_csv(os.getenv("ADMIN_USER_IDS", ""))

CORS_ORIGINS = _split_csv(os.getenv("CORS_ORIGINS", ""))
ALLOW_DEV_CORS = os.getenv("ALLOW_DEV_CORS", "0") == "1"

PERSONAL_DATA_ENCRYPTION_KEY = os.getenv("PERSONAL_DATA_ENCRYPTION_KEY", "").strip()
RECIPE_ENCRYPT_KEY = os.getenv("RECIPE_ENCRYPT_KEY", "").strip()
ENCRYPTION_KEYS = os.getenv("ENCRYPTION_KEYS", "").strip()
ENCRYPTION_ACTIVE_KEY_ID = os.getenv("ENCRYPTION_ACTIVE_KEY_ID", "primary").strip()
ENCRYPTION_KEY_FILE = os.getenv(
    "ENCRYPTION_KEY_FILE",
    os.path.join(os.path.dirname(__file__), ".encryption_key"),
).strip()

# ===== 安全防护 =====

# 管理后台 IP 白名单（逗号分隔），为空则不限制
# 示例：ADMIN_ALLOWED_IPS=192.168.1.100,192.168.1.101
ADMIN_ALLOWED_IPS = _split_csv(os.getenv("ADMIN_ALLOWED_IPS", ""))

# 列表接口单页最大数量
MAX_PAGE_SIZE = int(os.getenv("MAX_PAGE_SIZE", "50"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()
LOG_TO_FILE = os.getenv("LOG_TO_FILE", "0" if IS_PRODUCTION else "1") == "1"
LOG_DIR = os.getenv("LOG_DIR", os.path.join(os.path.dirname(__file__), "logs")).strip()
SLOW_SQL_MS = int(os.getenv("SLOW_SQL_MS", "500"))
SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
SENTRY_TRACES_SAMPLE_RATE = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.05"))

STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local").strip().lower()
LOCAL_UPLOAD_DIR = os.getenv(
    "LOCAL_UPLOAD_DIR",
    os.path.join(os.path.dirname(__file__), "uploads"),
).strip()
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "").strip()
S3_REGION = os.getenv("S3_REGION", "us-east-1").strip()
S3_BUCKET = os.getenv("S3_BUCKET", "").strip()
S3_PRIVATE_BUCKET = os.getenv("S3_PRIVATE_BUCKET", "").strip()
S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID", "").strip()
S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY", "").strip()
S3_PUBLIC_BASE_URL = os.getenv("S3_PUBLIC_BASE_URL", "").strip().rstrip("/")

BAIDU_OCR_API_KEY = os.getenv("BAIDU_OCR_API_KEY", "").strip()
BAIDU_OCR_SECRET_KEY = os.getenv("BAIDU_OCR_SECRET_KEY", "").strip()
BAIDU_OCR_TOKEN_URL = os.getenv(
    "BAIDU_OCR_TOKEN_URL",
    "https://aip.baidubce.com/oauth/2.0/token",
).strip()
BAIDU_OCR_API_URL = os.getenv(
    "BAIDU_OCR_API_URL",
    "https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic",
).strip()

REDIS_URL = os.getenv("REDIS_URL", "").strip()
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "1") == "1"
TRUSTED_PROXY_IPS = _split_csv(os.getenv("TRUSTED_PROXY_IPS", ""))


def _read_secret(name: str) -> str:
    """Load a secret from NAME_FILE first, then NAME (Docker/K8s compatible)."""
    path = os.getenv(f"{name}_FILE", "").strip()
    if path:
        with open(path, encoding="utf-8") as secret_file:
            return secret_file.read().strip()
    return os.getenv(name, "").strip()


SMTP_PASSWORD = _read_secret("SMTP_PASSWORD")

VERIFICATION_CHANNEL = os.getenv("VERIFICATION_CHANNEL", "debug").strip().lower()
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = os.getenv("SMTP_PORT", "465").strip()
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_FROM = os.getenv("SMTP_FROM", "").strip()
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "1").strip()


def validate_runtime_config() -> None:
    """Fail fast when an unsafe configuration is used in production."""
    if not IS_PRODUCTION:
        return

    errors: list[str] = []
    if RATE_LIMIT_ENABLED and not REDIS_URL:
        errors.append("生产环境启用应用限流时必须配置 REDIS_URL")
    weak_auth_secrets = {"", "dev-change-me", "change-me", "yunyao-prod-secret-change-me"}
    if AUTH_SECRET in weak_auth_secrets or len(AUTH_SECRET) < 32:
        errors.append("AUTH_SECRET 必须是至少 32 位的随机值")
    if not _DATABASE_URL_FROM_ENV:
        errors.append("DATABASE_URL 必须显式配置，禁止使用开发默认数据库")
    if ALLOW_DEV_CORS:
        errors.append("生产环境禁止 ALLOW_DEV_CORS")
    if not CORS_ORIGINS or "*" in CORS_ORIGINS:
        errors.append("生产环境必须配置明确的 CORS_ORIGINS")
    insecure_origins = [origin for origin in CORS_ORIGINS if not origin.startswith("https://")]
    if insecure_origins:
        errors.append("生产环境 CORS_ORIGINS 只允许 HTTPS 来源")
    if STORAGE_BACKEND != "s3":
        errors.append("生产环境 STORAGE_BACKEND 必须使用 s3")
    if not all((S3_BUCKET, S3_PRIVATE_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_PUBLIC_BASE_URL)):
        errors.append("生产环境必须完整配置 S3 对象存储")
    if S3_PUBLIC_BASE_URL.startswith("http://"):
        errors.append("生产环境 S3_PUBLIC_BASE_URL 只允许 HTTPS 或站内相对路径")
    if S3_PRIVATE_BUCKET == S3_BUCKET:
        errors.append("S3_PRIVATE_BUCKET 必须与公开图片桶分离")
    if VERIFICATION_CHANNEL not in {"email", "sms"}:
        errors.append("生产环境 VERIFICATION_CHANNEL 必须是 email 或 sms")
    if VERIFICATION_CHANNEL == "email" and not all((SMTP_HOST, SMTP_USERNAME, SMTP_FROM, SMTP_PASSWORD)):
        errors.append("邮件验证码必须完整配置 SMTP_HOST/SMTP_USERNAME/SMTP_FROM/SMTP_PASSWORD_FILE")

    has_key_file = bool(ENCRYPTION_KEY_FILE and os.path.isfile(ENCRYPTION_KEY_FILE))
    if not ENCRYPTION_KEYS and not PERSONAL_DATA_ENCRYPTION_KEY and not has_key_file:
        errors.append("必须配置 PERSONAL_DATA_ENCRYPTION_KEY 或挂载 ENCRYPTION_KEY_FILE")
    if not ENCRYPTION_KEYS and not RECIPE_ENCRYPT_KEY and not has_key_file:
        errors.append("必须配置 RECIPE_ENCRYPT_KEY 或挂载 ENCRYPTION_KEY_FILE")

    if errors:
        raise RuntimeError("生产配置不安全：" + "；".join(errors))


validate_runtime_config()
