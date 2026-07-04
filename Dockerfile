FROM python:3.13-slim

RUN pip install --no-cache-dir numpy

WORKDIR /app

COPY . .

RUN chmod +x docker-entrypoint.sh

EXPOSE 8080

ENV BUNDLE_PATH=/app/data/2026-07-02-matin \
    PORT_DEMO=8100 \
    PORT_SERVE=8080

ENTRYPOINT ["./docker-entrypoint.sh"]
