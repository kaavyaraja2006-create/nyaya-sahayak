# NyayaSahayak API
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# The API imports `agents` and `ai_engine` from the repository root.
COPY backend/ /app/backend/
COPY agents/ /app/agents/
COPY ai_engine/ /app/ai_engine/
COPY legal_data/ /app/legal_data/
COPY pytest.ini /app/pytest.ini

ENV PYTHONPATH=/app \
    DATA_DIR=/app/backend/data \
    AUTHORITY_CORPUS_DIR=/app/legal_data/authorities

RUN mkdir -p /app/backend/data

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
