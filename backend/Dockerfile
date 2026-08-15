FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# install deps first (better layer caching)
COPY pyproject.toml .
RUN pip install --upgrade pip && pip install .

# app code
COPY . .

# start.sh runs `alembic upgrade head` then launches uvicorn on $PORT
CMD ["bash", "start.sh"]