# Master node DFS-X. Hanya pustaka standar Python, tanpa pip install,
# supaya image tetap kecil dan bisa dibangun tanpa akses PyPI.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY common/ /app/common/
COPY master/ /app/master/

RUN mkdir -p /data

EXPOSE 9100

CMD ["python", "/app/master/app.py"]
