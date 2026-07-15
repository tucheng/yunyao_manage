"""Structured logging, request metrics, slow SQL and optional Sentry tracing."""

from __future__ import annotations

import contextvars
import json
import logging
import time
from datetime import datetime, timezone

from prometheus_client import Counter, Histogram
from sqlalchemy import event

from app_config import APP_ENV, SENTRY_DSN, SENTRY_TRACES_SAMPLE_RATE, SLOW_SQL_MS

request_id_var = contextvars.ContextVar("request_id", default="-")

HTTP_REQUESTS = Counter("yunyao_http_requests_total", "HTTP requests", ("method", "route", "status"))
HTTP_DURATION = Histogram(
    "yunyao_http_request_duration_seconds", "HTTP request latency", ("method", "route"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
SQL_DURATION = Histogram(
    "yunyao_sql_duration_seconds", "SQL statement latency", ("operation",),
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
VERIFICATION_SENDS = Counter("yunyao_verification_send_total", "Verification sends", ("channel", "result"))
UPLOADS = Counter("yunyao_upload_total", "Upload attempts", ("kind", "result"))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for key in ("method", "path", "status", "duration_ms", "client_ip", "operation"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_json_logging(level: str, handlers: list[logging.Handler]) -> None:
    formatter = JsonFormatter()
    for handler in handlers:
        handler.setFormatter(formatter)
    logging.basicConfig(level=getattr(logging, level, logging.INFO), handlers=handlers, force=True)


def init_error_tracking() -> None:
    if not SENTRY_DSN:
        return
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    sentry_sdk.init(
        dsn=SENTRY_DSN, environment=APP_ENV,
        integrations=[FastApiIntegration(), SqlalchemyIntegration()],
        traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE, send_default_pii=False,
    )


def instrument_sql(engine) -> None:
    logger = logging.getLogger("yunyao.sql")

    @event.listens_for(engine, "before_cursor_execute")
    def before_cursor_execute(_conn, _cursor, _statement, _params, context, _many):
        context._yunyao_started_at = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def after_cursor_execute(_conn, _cursor, statement, _params, context, _many):
        started = getattr(context, "_yunyao_started_at", None)
        if started is None:
            return
        elapsed = time.perf_counter() - started
        operation = (statement.lstrip().split(None, 1) or ["unknown"])[0].upper()
        SQL_DURATION.labels(operation=operation).observe(elapsed)
        if elapsed * 1000 >= SLOW_SQL_MS:
            logger.warning("slow_sql", extra={"duration_ms": round(elapsed * 1000, 2), "operation": operation})
