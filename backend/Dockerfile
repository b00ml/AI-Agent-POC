FROM python:3.12-slim

WORKDIR /app

# PaddleOCR 所需系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖（后端 + 核心 + 本地 PaddleOCR）
COPY backend/requirements.txt /app/backend/
COPY requirements.txt requirements-paddle.txt /app/
RUN pip install --no-cache-dir -r /app/backend/requirements.txt \
    && pip install --no-cache-dir -r /app/requirements.txt \
    && pip install --no-cache-dir -r /app/requirements-paddle.txt

# 复制代码（与本地相同目录结构）
COPY backend/app/ /app/backend/app/
COPY core/ /app/core/
COPY data/ /app/data/
COPY bank/ /app/bank/
COPY doc/ /app/doc/
RUN mkdir -p /app/output/reports /app/output/cache

# 环境变量
ENV PYTHONPATH=/app:/app/backend
ENV OCR_ENGINE=paddle
ENV FLAGS_use_mkldnn=0 \
    FLAGS_enable_pir_api=0 \
    OMP_NUM_THREADS=1 \
    PYTHONIOENCODING=utf-8

# 预热本地 OCR 模型（构建期下载，运行期离线）
RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(type='ocr', use_angle_cls=True, lang='ch', show_log=False)"

EXPOSE 8000

# Liveness only: external ERP, OCR and LLM providers are intentionally not
# required for the container to become healthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()"]

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
