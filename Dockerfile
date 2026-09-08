# 启衡精密 AI 财务提效 POC · 单容器交付
# 本地 PaddleOCR（默认，发票不出域）+ Streamlit Web 界面
FROM python:3.12-slim

WORKDIR /app

# PaddleOCR 运行所需系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖（本地 PaddleOCR + 核心依赖）
COPY requirements.txt requirements-paddle.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-paddle.txt

# 复制项目代码
COPY . .

# 预热并固化本地 OCR 模型（构建期下载，运行期完全离线）
ENV FLAGS_use_mkldnn=0 \
    FLAGS_enable_pir_api=0 \
    OMP_NUM_THREADS=1
RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(type='ocr', use_angle_cls=True, lang='ch', show_log=False)" \
    && mkdir -p output/reports output/cache

# 默认本地 OCR：发票图片不出域
ENV OCR_ENGINE=paddle
ENV PYTHONIOENCODING=utf-8
ENV PYTHONUNBUFFERED=1

# Streamlit
EXPOSE 8501

# Liveness only: this endpoint does not make an ERP or model call.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3).read()"]

ENTRYPOINT ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.headless=true"]
