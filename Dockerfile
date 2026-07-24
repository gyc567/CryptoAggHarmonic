# For more information, please refer to https://aka.ms/vscode-docker-python
FROM python:3-slim

EXPOSE 5000

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

# Set your open API key ( un comment the line below )
# ENV OPENAI_API_KEY=YOUR_KEY_GOES_HERE
# ENV OPENAI_API_MODEL=gpt-3.5-turbo
# ENV OPENAI_API_BASE_URL=https://api.openai.com/v1

# Install pip requirements
COPY requirements.txt .
RUN python -m pip install -r requirements.txt

WORKDIR /app
COPY . /app

# Creates a non-root user with an explicit UID and adds permission to access the /app folder
# For more info, please refer to https://aka.ms/vscode-docker-python-configure-containers
RUN adduser -u 5678 --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

# During debugging, this entry point will be overridden. For more information, please refer to https://aka.ms/vscode-docker-python-debug
# gunicorn.conf.py: gevent worker（SSE 长连接）+ 多进程（CPU 并行）
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app.main:app"]
