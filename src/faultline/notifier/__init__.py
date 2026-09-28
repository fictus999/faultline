"""Notifier process: relays alert events from the Postgres outbox to CloudWatch, SNS and
n8n, with retries, rate limits and a circuit breaker per sink. A slow or failing sink can
never stall detection.
"""
