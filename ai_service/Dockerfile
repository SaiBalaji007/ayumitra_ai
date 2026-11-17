# AyuMitra AI service (CPU image): OCR, NLP, retrieval, reranking, citation validation, LangGraph.
# The LLM runs in a separate container (llama.cpp on CPU, or vLLM on a GPU host).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HF_HOME=/data/hf-cache \
    AYUMITRA_DATA_DIR=/data/ai

RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY ayumitra_ai ./ayumitra_ai
COPY knowledge ./knowledge
COPY evaluation ./evaluation

RUN useradd --create-home --uid 10001 ayumitra && mkdir -p /data && chown ayumitra /data
USER ayumitra
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=8)"
CMD ["uvicorn", "ayumitra_ai.api:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
