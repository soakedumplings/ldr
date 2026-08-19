FROM python:3.12-slim

WORKDIR /app

# Install deps first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# SQLite lives on a persistent volume on the host so streaks survive restarts.
# (Fly.io: mount a volume at /data and set DB_PATH=/data/ldr.db)
ENV DB_PATH=/data/ldr.db

CMD ["python", "bot.py"]
