FROM python:3.9-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir flask requests

WORKDIR /app

COPY app.py ./
COPY hls_downloader.py ./
COPY templates ./templates/

RUN mkdir -p /data/config /data/downloads /data/logs

EXPOSE 8080

CMD ["python", "app.py"]
