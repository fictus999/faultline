# Security

Report a vulnerability through a private GitHub security advisory on this repository, not a
public issue.

## Controls in place

| Area | Control | Where |
| --- | --- | --- |
| Log ingestion | Lines capped at 8 KB, control characters stripped, strict line format | `collector/parser.py` |
| Secrets in logs | AWS access keys, bearer tokens and email addresses redacted before storage | `collector/parser.py` |
| Webhooks | HMAC-SHA256 over timestamp and body, constant-time compare, 300 s replay window, `event_id` dedupe | `common/signing.py`, n8n workflow |
| Database | Parameterized SQL only; `UNIQUE (event_id, sink)` makes retries idempotent | `db/schema.sql` |
| API surface | Bound to 127.0.0.1; chaos endpoints exist only when `FAULTLINE_DEMO_MODE=1`; service names validated | `api/app.py` |
| Containers | Non-root user (uid 10001), slim base image, Trivy scan in CI | `Dockerfile`, CI |
| Supply chain | GitHub Actions pinned to commit SHAs; gitleaks secret scan in CI | `.github/workflows/ci.yml` |
| Cloud access | Least-privilege IAM: the notifier can only publish to one SNS topic and write one log group. CI uses GitHub OIDC, with no stored AWS keys | `infra/terraform` |
| Configuration | Secrets come from `.env` (gitignored); the webhook URL must be http(s) | `common/config.py` |

## Known gaps

- The WebSocket feed and the console are unauthenticated. This is acceptable only while bound
  to 127.0.0.1 (`TODO(security)` in `api/app.py`).
- The laptop demo uses static AWS keys for a least-privilege IAM user. Production would use
  an instance or task role.
- Redis and Postgres use development credentials inside the Compose network and are not
  published to the host.
