from fastapi import HTTPException


class QuotaExceeded(HTTPException):
    """Expected business rejection used when a daily quota is unavailable."""

    def __init__(self, quota_kind: str, detail: str) -> None:
        super().__init__(status_code=403, detail=detail)
        self.code = "QUOTA_EXHAUSTED"
        self.quota_kind = quota_kind
        self.remaining = 0
