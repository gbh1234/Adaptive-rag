FROM node:24-alpine AS frontend
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json /web/
RUN npm ci
COPY frontend /web/
RUN npm run build

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY pyproject.toml README.md /app/
COPY app /app/app
COPY knowledge /app/knowledge
COPY --from=frontend /web/dist /app/frontend/dist
RUN pip install --upgrade pip && pip install ".[rerank]" \
    && mkdir -p /app/data/local \
    && chown -R appuser:appuser /app

USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
