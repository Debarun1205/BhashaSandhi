FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/home/app/hf TTS_PRELOAD=hi,bn

RUN useradd -m -u 1000 app
WORKDIR /app

# CPU-only PyTorch keeps the image small (no GPU needed for MMS-TTS).
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt requirements-local-stt.txt ./
RUN pip install -r requirements.txt
ARG INSTALL_LOCAL_STT=0
RUN if [ "$INSTALL_LOCAL_STT" = "1" ]; then pip install -r requirements-local-stt.txt; fi

COPY --chown=app:app . .
RUN mkdir -p /app/data && chown app:app /app/data
USER app

# Bake the three open-weight MMS-TTS voices into the image so cold starts don't download them.
RUN python -c "from transformers import AutoTokenizer, VitsModel; [(AutoTokenizer.from_pretrained('facebook/mms-tts-'+c), VitsModel.from_pretrained('facebook/mms-tts-'+c)) for c in ('hin','ben','ory')]" \
    || echo "WARNING: could not prefetch MMS voices; they will download on first use"

EXPOSE 8080
CMD ["sh", "-c", "gunicorn app:app --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 120"]
