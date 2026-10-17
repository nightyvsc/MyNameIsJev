FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    MAIL_DB_PATH=/data/mail.sqlite3 SMTP_HOST=0.0.0.0 SMTP_PORT=2525
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY world ./world
RUN pip install --no-cache-dir '.[world]'
EXPOSE 2525 3002
CMD ["uvicorn", "world.mail.app:app", "--host", "0.0.0.0", "--port", "3002"]
