# 로컬 HTTP 어댑터 이미지. 빌드 컨텍스트는 backend/ (docker-compose.yml의 api 서비스).
FROM python:3.12-slim

WORKDIR /app
COPY src/requirements.txt /tmp/src-requirements.txt
COPY local/adapter/requirements.txt /tmp/adapter-requirements.txt
RUN pip install --no-cache-dir -r /tmp/src-requirements.txt -r /tmp/adapter-requirements.txt

COPY src/ /app/src/
COPY local/adapter/app.py /app/adapter/app.py

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PORT=3000
EXPOSE 3000
CMD ["python", "/app/adapter/app.py"]
