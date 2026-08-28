FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app/backend

RUN apt-get update \
  && apt-get install -y --no-install-recommends libatomic1 \
  && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/app ./app
COPY courses /app/courses

ENV PATH="/app/backend/.venv/bin:${PATH}"
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
