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


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:root@localhost:3306/yunyao?charset=utf8mb4",
)

AUTH_SECRET = os.getenv("AUTH_SECRET", "dev-change-me")
ACCESS_TOKEN_EXPIRE_SECONDS = int(os.getenv("ACCESS_TOKEN_EXPIRE_SECONDS", "604800"))

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
ADMIN_USER_IDS = _split_int_csv(os.getenv("ADMIN_USER_IDS", ""))

CORS_ORIGINS = _split_csv(os.getenv("CORS_ORIGINS", ""))
ALLOW_DEV_CORS = os.getenv("ALLOW_DEV_CORS", "1") == "1"

WX_APPID = os.getenv("WX_APPID", "")
WX_SECRET = os.getenv("WX_SECRET", "")
ENABLE_MOCK_LOGIN = os.getenv("ENABLE_MOCK_LOGIN", "1") == "1"
