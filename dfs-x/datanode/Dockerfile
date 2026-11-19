# Data node DFS-X. Satu image dipakai semua data node; identitas dan
# kapasitas dibedakan lewat variabel lingkungan di docker-compose.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY common/ /app/common/
COPY datanode/ /app/datanode/

RUN mkdir -p /data/chunks

EXPOSE 9101

CMD ["python", "/app/datanode/app.py"]
