FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

# Data directory for the SQLite file -- mounted as a volume in compose
# so the database survives container rebuilds.
RUN mkdir -p /data

EXPOSE 8000

# Seed runs every startup but is idempotent (skips if questions already exist),
# then launches the server. This means dropping new questions into seed_questions.json
# and rebuilding will NOT auto-add them once the DB has data -- see README for how to reseed.
CMD ["sh", "-c", "python3 seed.py && uvicorn main:app --host 0.0.0.0 --port 8000"]
