FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libportaudio2 alsa-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY audio_link.py admin.py ./
COPY web ./web
ENV PYTHONUNBUFFERED=1
CMD ["python", "/app/admin.py", "--host", "0.0.0.0", "--data-dir", "/data"]
