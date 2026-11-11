# MediFed coordinator API on a Hugging Face Space (Docker SDK, CPU basic).
# Built by scripts/deploy_space.py, which copies backend/, ml/, analytics/ and run.py next to this file.
# Every setting comes from the Space's secrets and variables (docs/deploy.md); nothing secret is in the image.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libgomp1: OpenMP runtime for PyTorch and scikit-learn.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face runs the container as user 1000.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
WORKDIR /home/user/app

# CPU-only PyTorch, the same versions as the hospital agent so the model architectures match exactly.
RUN pip install --user torch==2.15.0 torchvision==0.29.2 --index-url https://download.pytorch.org/whl/cpu
COPY --chown=user backend/requirements.txt backend/requirements-optional.txt backend/
RUN pip install --user -r backend/requirements.txt "statsmodels>=0.14" "prophet>=1.1.5"

COPY --chown=user . .

# Fixed for the container; everything else is set in the Space's settings.
ENV API_HOST=0.0.0.0 \
    PORT=7860 \
    MODEL_STORAGE_PATH=/tmp/medifed/models \
    HOSPITAL_DATA_ROOT=/tmp/medifed/hospitals \
    MODEL_WEIGHTS_IN_DATABASE=true \
    TRUST_PROXY_HEADERS=true

EXPOSE 7860
CMD ["python", "run.py"]
