FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TF_CPP_MIN_LOG_LEVEL=2 \
    DEEPFACE_HOME=/opt/deepface \
    FACE_APP_ENV=production \
    FACE_APP_DATA_DIR=/data

WORKDIR /app

# System libraries that OpenCV and MediaPipe load at import time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libegl1 libgles2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-ai.txt ./
RUN pip install -r requirements-ai.txt

# Bake the models in so the first start needs no download.
RUN mkdir -p models/tts /opt/deepface \
    && python -m piper.download_voices vi_VN-vais1000-medium --download-dir models/tts \
    && python -c "from deepface import DeepFace; DeepFace.build_model('Facenet')"

COPY src ./src

RUN useradd --system --uid 1000 --no-create-home app \
    && mkdir /data \
    && chown -R app /data /opt/deepface
USER app
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health', timeout=8)"

# One process only: SQLite, the cache and the login throttle live in this process.
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
