FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    JEV_GATE_DB=/var/lib/jev-gate/audit.sqlite3

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY docs ./docs
RUN pip install --no-cache-dir . \
    && mkdir -p /var/lib/jev-gate \
    && chown -R 10001:10001 /var/lib/jev-gate

USER 10001:10001
EXPOSE 8000
CMD ["jev-gate"]
