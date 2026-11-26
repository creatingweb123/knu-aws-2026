# 로컬 HTTP 어댑터 이미지. 빌드 컨텍스트는 backend/ (docker-compose.yml의 api 서비스).
FROM python:3.12-slim

WORKDIR /app
COPY src/requirements.txt /tmp/src-requirements.txt
COPY src/ai-requirements.lock /tmp/ai-requirements.lock
COPY local/adapter/requirements.txt /tmp/adapter-requirements.txt
RUN pip install --no-cache-dir -r /tmp/src-requirements.txt -r /tmp/adapter-requirements.txt
# AiCardFunction과 같은 AI 의존성(해시 고정 잠금 파일, 6a). 같은 핸들러를 같은 버전으로 부른다.
RUN pip install --no-cache-dir --only-binary=:all: --no-deps --require-hashes -r /tmp/ai-requirements.lock
# Asia/Seoul 시간대 데이터 확인(없으면 코드가 UTC+9 고정 오프셋으로 대신한다. 결과는 같다).
RUN python -c "from zoneinfo import ZoneInfo; ZoneInfo('Asia/Seoul')" && echo "tzdata ok" || echo "tzdata missing: UTC+9 fallback"

COPY src/ /app/src/
COPY local/adapter/app.py /app/adapter/app.py

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PORT=3000
EXPOSE 3000
CMD ["python", "/app/adapter/app.py"]
