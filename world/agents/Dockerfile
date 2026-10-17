FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY contracts ./contracts
COPY src ./src
COPY world ./world
RUN pip install --no-cache-dir .
ENTRYPOINT ["python", "-m"]
