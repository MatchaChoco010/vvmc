# syntax=docker/dockerfile:1
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app

# fugashi / unidic-lite は manylinux wheel があるので追加の apt パッケージは不要。
# PYTHONPATH=/app なので /app/app が最優先で解決される。dev 時に
# /app/app が volume で上書きされてもそのまま import される(ホット reload と整合)。
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
