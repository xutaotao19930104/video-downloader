FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY templates ./templates/

RUN mkdir -p /data/config /data/downloads /data/logs /data/temp

EXPOSE 8080

CMD ["python", "app.py"]
