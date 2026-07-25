FROM python:3.9-slim

RUN apt-get update && apt-get install -y --no-install-recommends wget xz-utils && \
    wget -q https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz -O /tmp/ffmpeg.tar.xz && \
    tar -xf /tmp/ffmpeg.tar.xz -C /tmp && \
    cp /tmp/ffmpeg-master-latest-linux64-gpl/bin/ffmpeg /usr/local/bin/ && \
    cp /tmp/ffmpeg-master-latest-linux64-gpl/bin/ffprobe /usr/local/bin/ && \
    chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe && \
    rm -rf /tmp/ffmpeg* /var/lib/apt/lists/*

RUN pip install --no-cache-dir flask requests cloudscraper

WORKDIR /app

COPY app.py ./
COPY hls_downloader.py ./
COPY templates ./templates/

RUN mkdir -p /data/config /data/downloads /data/logs

EXPOSE 8080

CMD ["python", "app.py"]
