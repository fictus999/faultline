"""Runtime configuration, read from environment variables."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

LOG_STREAM = "faultline:logs"
UI_CHANNEL = "faultline:ui"
STATS_KEY = "faultline:stats"
CHAOS_PREFIX = "faultline:chaos:"
SINK_CHAOS_PREFIX = "faultline:chaos-sink:"
COLLECTOR_CHECKPOINT_KEY = "faultline:collector:checkpoint"
SERVICE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


@dataclass(frozen=True)
class Config:
    redis_url: str
    database_url: str
    log_path: str
    sinks: tuple[str, ...]
    webhook_url: str
    webhook_secret: str
    sns_topic_arn: str
    cloudwatch_log_group: str
    aws_region: str
    demo_mode: bool
    api_host: str
    api_port: int
    frontend_dir: str

    @classmethod
    def from_env(cls) -> Config:
        env = os.environ.get
        webhook_url = env(
            "FAULTLINE_WEBHOOK_URL", "http://localhost:8080/api/demo/webhook-receiver"
        )
        if not webhook_url.startswith(("http://", "https://")):
            raise ValueError("FAULTLINE_WEBHOOK_URL must be an http(s) URL")
        return cls(
            redis_url=env("FAULTLINE_REDIS_URL", "redis://localhost:6379/0"),
            database_url=env(
                "FAULTLINE_DATABASE_URL",
                "postgresql://faultline:faultline@localhost:5432/faultline",
            ),
            log_path=env("FAULTLINE_LOG_PATH", "var/log/app.log"),
            sinks=tuple(s.strip() for s in env("FAULTLINE_SINKS", "log,webhook").split(",") if s),
            webhook_url=webhook_url,
            # Dev-only default; compose and real deployments must override it.
            webhook_secret=env("FAULTLINE_WEBHOOK_SECRET", "dev-only-secret"),
            sns_topic_arn=env("FAULTLINE_SNS_TOPIC_ARN", ""),
            cloudwatch_log_group=env("FAULTLINE_CW_LOG_GROUP", ""),
            aws_region=env("AWS_REGION", "ap-south-1"),
            demo_mode=env("FAULTLINE_DEMO_MODE", "1") == "1",
            api_host=env("FAULTLINE_API_HOST", "127.0.0.1"),
            api_port=int(env("FAULTLINE_API_PORT", "8080")),
            frontend_dir=env("FAULTLINE_FRONTEND_DIR", "frontend"),
        )
