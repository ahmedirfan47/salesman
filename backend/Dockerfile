FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# copy everything first, then install (the package needs app/ to exist at build time)
COPY . .

RUN pip install .

# start.sh runs `alembic upgrade head` then launches uvicorn on $PORT
CMD ["bash", "start.sh"]