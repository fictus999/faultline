FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FAULTLINE_FRONTEND_DIR=/app/frontend

WORKDIR /app
RUN useradd --create-home --uid 10001 faultline \
    && mkdir -p /var/log/faultline \
    && chown faultline /var/log/faultline

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY tools ./tools
COPY frontend ./frontend
RUN chmod -R a+rX /app

# Every process runs as an unprivileged user.
USER faultline
CMD ["faultline", "--help"]
