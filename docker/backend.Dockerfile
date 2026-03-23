FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY . .

FROM python:3.12-slim

WORKDIR /app
COPY --from=builder /app /app

RUN useradd --create-home appuser \
    && mkdir -p /app/sessions \
    && chown -R appuser:appuser /app
USER appuser

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
