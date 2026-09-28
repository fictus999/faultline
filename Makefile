.PHONY: up down reset logs ps inject recover break-webhook heal-webhook kill-notifier start-notifier n8n check

up:              ## build and start everything; console at http://127.0.0.1:8080
	docker compose up --build -d
down:
	docker compose down
reset:           ## wipe alerts, stream and logs
	docker compose down -v
logs:
	docker compose logs -f --tail=50 collector detector notifier api
ps:
	docker compose ps
inject:          ## payments starts failing (35% errors)
	curl -s -X POST localhost:8080/api/chaos/services/payments -H 'content-type: application/json' -d '{"error_rate":0.35}'
recover:
	curl -s -X DELETE localhost:8080/api/chaos/services/payments
break-webhook:
	curl -s -X POST localhost:8080/api/chaos/sinks/webhook
heal-webhook:
	curl -s -X DELETE localhost:8080/api/chaos/sinks/webhook
kill-notifier:   ## alerts queue in the Postgres outbox
	docker compose kill notifier
start-notifier:  ## the outbox drains, CRITICAL first
	docker compose start notifier
n8n:             ## n8n intake workflow (UI http://127.0.0.1:5678); webhook deliveries now go to n8n
	docker compose --profile n8n run --rm n8n import:workflow --input=/workflows/faultline-intake.json
	docker compose --profile n8n run --rm n8n update:workflow --id=faultlineIntake1 --active=true
	docker compose --profile n8n up -d --force-recreate n8n
	FAULTLINE_WEBHOOK_URL=http://n8n:5678/webhook/faultline docker compose up -d notifier
check:
	uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
