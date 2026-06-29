FROM python:3.12-slim

WORKDIR /app

# Systeemafhankelijkheden voor psycopg en builds blijven minimaal.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# DigitalOcean App Platform zet $PORT (meestal 8080).
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
