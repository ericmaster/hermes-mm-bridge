FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py config.py entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 3088

ENTRYPOINT ["/app/entrypoint.sh"]
