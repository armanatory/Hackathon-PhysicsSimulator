# QuietOffice backend: FastAPI + Allsolve SDK
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Same folder shape as the repository, because app/config.py resolves paths from it.
WORKDIR /srv/quiet-office/backend

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY sim ./sim

# Run as a normal user. The SDK writes its cache into this folder.
RUN useradd --create-home --uid 10001 quiet && chown -R quiet:quiet /srv/quiet-office
USER quiet

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

# One worker on purpose: run state is kept in memory.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
