FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so code changes don't bust the layer cache.
COPY pyproject.toml README.md ./
COPY review_responder/__init__.py review_responder/__init__.py
ARG LLM_EXTRAS="anthropic,groq,openai,google"
RUN pip install ".[${LLM_EXTRAS}]" && pip uninstall -y review-responder

COPY review_responder ./review_responder
COPY examples ./examples
RUN pip install --no-deps . \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /data && chown app:app /data

USER app
ENV STATE_DB=/data/state.db
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["uvicorn", "review_responder.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
