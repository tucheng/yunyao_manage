"""简单内存频率限制器

按 IP 分路由模式限流，滑动窗口算法。
"""
import json
import time
from collections import defaultdict
from starlette.responses import Response


class RateLimiter:
    """内存限流器"""

    def __init__(self):
        # {ip: [timestamp, ...]}
        self._records: dict[str, list[float]] = defaultdict(list)

    def _get_route_group(self, path: str) -> str:
        """根据路径分组，不同组用不同上限"""
        if path.startswith("/admin/"):
            return "admin"
        if path.startswith("/auth/"):
            return "auth"
        if path.startswith(("/recipes", "/works")):
            return "list"
        if path.startswith("/upload/"):
            return "upload"
        return "default"

    def _get_limit(self, group: str) -> tuple[int, int]:
        """返回 (max_requests, window_seconds)"""
        limits = {
            "auth":   (10, 60),    # 登录/注册/验证码：10次/分钟
            "admin":  (30, 60),    # 管理后台：30次/分钟
            "list":   (60, 60),    # 列表查询：60次/分钟
            "upload": (20, 60),    # 上传：20次/分钟
            "default": (120, 60),  # 其他：120次/分钟
        }
        return limits.get(group, (120, 60))

    def check(self, request):
        """检查当前请求是否超限，超限返回 429 Response，否则返回 None"""
        if request.method == "OPTIONS":
            return None

        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path
        group = self._get_route_group(path)
        max_req, window = self._get_limit(group)

        now = time.time()
        records = self._records[client_ip]

        # 清除窗口之前的记录
        cutoff = now - window
        self._records[client_ip] = [t for t in records if t > cutoff]

        if len(self._records[client_ip]) >= max_req:
            return Response(
                json.dumps({"detail": f"请求过于频繁，请稍后再试（{max_req}次/{window}秒）"}, ensure_ascii=False),
                status_code=429,
                media_type="application/json",
            )

        self._records[client_ip].append(now)
        return None
