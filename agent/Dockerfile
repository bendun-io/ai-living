FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src

# Run as an unprivileged account. The uid is pinned so bind-mounted files keep a
# predictable owner across rebuilds; /app/skills is mounted read-only at runtime.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin agent \
    && chown -R agent:agent /app
USER agent

EXPOSE 8000

# urllib rather than curl: the slim base has no curl, and a non-2xx status raises,
# so an agent that is up but failing readiness is reported unhealthy.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"

CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"]
