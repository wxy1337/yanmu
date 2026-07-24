FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-noto-cjk libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app
COPY run.py pyproject.toml ./
RUN mkdir -p /app/data/jobs

EXPOSE 8000
VOLUME ["/app/data", "/root/.cache/huggingface"]
CMD ["python", "run.py"]
