FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY app/main.py app/main.py
COPY app/sync_engine.py app/sync_engine.py
COPY app/static app/static
COPY parser parser
COPY database database
COPY .env.example .env.example

# Install Python packages
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" psycopg2-binary python-dotenv

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
