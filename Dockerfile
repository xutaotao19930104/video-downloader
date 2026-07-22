FROM python:3.9-slim

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir yt-dlp flask requests

WORKDIR /app

COPY app.py ./
COPY templates ./templates/

RUN mkdir -p /data/config /data/downloads /data/logs

EXPOSE 8080

CMD ["python", "app.py"]
