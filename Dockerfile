FROM python:3.13-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ server/
COPY static/ static/
COPY data/ data/
COPY config.example.json config.example.json
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENV HOST=0.0.0.0
ENV HTTP_PORT=8080
ENV HTTPS_PORT=8443

EXPOSE 8080 8443

VOLUME ["/data"]

ENTRYPOINT ["/docker-entrypoint.sh"]
