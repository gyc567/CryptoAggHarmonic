# Backend Flask API for Pyharmonics GPT.
# Production secrets must be injected at runtime via environment variables or
# Docker secrets; do not bake them into the image.
FROM python:3.11-slim

EXPOSE 5000

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install pip requirements first for better layer caching
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . /app

# Creates a non-root user with an explicit UID and adds permission to access the /app folder
RUN adduser -u 5678 --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

# Health check against the Flask health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/health', timeout=4)" || exit 1

# gunicorn.conf.py: gthread worker + multi-process (CPU parallelism)
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app.main:app"]
