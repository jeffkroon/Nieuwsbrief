FROM python:3.12-slim

WORKDIR /app

# Systeemafhankelijkheden voor psycopg en builds blijven minimaal.
# Vergrendelde versies (uit requirements.txt via uv pip compile): elke build krijgt
# exact dezelfde pakketten als waarmee getest is, geen stille upgrades bij een deploy.
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

COPY . .

# DigitalOcean App Platform zet $PORT (meestal 8080).
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
