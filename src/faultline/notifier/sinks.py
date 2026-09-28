"""Delivery sinks. Each is independent: one failing sink never blocks the others."""

from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from typing import Any, Protocol

import structlog

from faultline.common.config import Config
from faultline.common.signing import sign

log = structlog.get_logger()


class SinkError(Exception):
    pass


class Sink(Protocol):
    name: str

    async def send(self, event: dict[str, Any]) -> None: ...


class LogSink:
    """Always-on local sink: the notifier's own structured log."""

    name = "log"

    async def send(self, event: dict[str, Any]) -> None:
        log.info(
            "alert_delivered",
            sink=self.name,
            event_id=event["event_id"],
            type=event["type"],
            alert_service=event["service"],
            severity=event["severity"],
        )


class WebhookSink:
    """HMAC-signed POST, e.g. to n8n. The receiver verifies it and dedupes by event_id."""

    name = "webhook"

    def __init__(self, url: str, secret: str) -> None:
        self.url = url
        self.secret = secret

    async def send(self, event: dict[str, Any]) -> None:
        body = json.dumps(event, separators=(",", ":"), sort_keys=True).encode()
        ts = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            "X-Faultline-Timestamp": ts,
            "X-Faultline-Signature": sign(self.secret, ts, body),
            "X-Faultline-Event-Id": event["event_id"],
        }
        await asyncio.to_thread(_post, self.url, body, headers)


def _post(url: str, body: bytes, headers: dict[str, str]) -> None:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    # URL comes from deploy config and is checked to be http(s) in Config.from_env.
    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
        if response.status >= 300:
            raise SinkError(f"webhook returned HTTP {response.status}")


class SnsSink:
    name = "sns"

    def __init__(self, topic_arn: str, region: str) -> None:
        import boto3

        self.topic_arn = topic_arn
        self.client = boto3.client("sns", region_name=region)

    async def send(self, event: dict[str, Any]) -> None:
        subject = f"[{event['severity']}] {event['service']} {event['type']}"[:100]
        await asyncio.to_thread(
            self.client.publish,
            TopicArn=self.topic_arn,
            Subject=subject,
            Message=json.dumps(event, indent=2),
            MessageAttributes={
                "event_id": {"DataType": "String", "StringValue": event["event_id"]}
            },
        )


class CloudWatchSink:
    name = "cloudwatch"
    stream = "alerts"

    def __init__(self, log_group: str, region: str) -> None:
        import boto3

        self.log_group = log_group
        self.client = boto3.client("logs", region_name=region)
        self._stream_ready = False

    async def send(self, event: dict[str, Any]) -> None:
        await asyncio.to_thread(self._put, event)

    def _put(self, event: dict[str, Any]) -> None:
        if not self._stream_ready:
            try:
                self.client.create_log_stream(
                    logGroupName=self.log_group, logStreamName=self.stream
                )
            except self.client.exceptions.ResourceAlreadyExistsException:
                pass
            self._stream_ready = True
        self.client.put_log_events(
            logGroupName=self.log_group,
            logStreamName=self.stream,
            logEvents=[{"timestamp": int(time.time() * 1000), "message": json.dumps(event)}],
        )


def build_sinks(cfg: Config) -> dict[str, Sink]:
    sinks: dict[str, Sink] = {}
    for name in cfg.sinks:
        if name == "log":
            sinks[name] = LogSink()
        elif name == "webhook":
            sinks[name] = WebhookSink(cfg.webhook_url, cfg.webhook_secret)
        elif name == "sns" and cfg.sns_topic_arn:
            sinks[name] = SnsSink(cfg.sns_topic_arn, cfg.aws_region)
        elif name == "cloudwatch" and cfg.cloudwatch_log_group:
            sinks[name] = CloudWatchSink(cfg.cloudwatch_log_group, cfg.aws_region)
        else:
            log.warning("sink_not_configured", sink=name)
    return sinks
