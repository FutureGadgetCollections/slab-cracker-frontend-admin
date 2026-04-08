FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY psa_proxy.py .

ENV PSA_PROXY_PORT=3001
ENV PSA_PROXY_BIND=0.0.0.0
ENV PSA_PROXY_API_KEY=

EXPOSE 3001

CMD ["python", "psa_proxy.py"]
