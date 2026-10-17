FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SOCIAL_DB_PATH=/data/social.sqlite3
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY world ./world
RUN pip install --no-cache-dir '.[world]'
EXPOSE 3003
CMD ["uvicorn", "world.social.app:app", "--host", "0.0.0.0", "--port", "3003"]
