FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements-server.txt .
RUN python -m pip install --no-cache-dir -r requirements-server.txt \
    && addgroup --system duck \
    && adduser --system --ingroup duck duck

COPY duckserver/ ./duckserver/
COPY protocol.py rules.py ./

USER duck

EXPOSE 11940/tcp

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,socket; s=socket.create_connection(('127.0.0.1',int(os.environ.get('DUCK_PORT','11940'))),timeout=3); s.close()" || exit 1

ENTRYPOINT ["python", "-m", "duckserver"]
