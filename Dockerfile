FROM python:3.11-slim

# HF Spaces requires non-root user with UID 1000
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

# Install dependencies first (cache layer)
COPY --chown=user backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the embedding model into the image so cold starts don't re-download (~570MB)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"

# Copy backend source
COPY --chown=user backend/ .

# HF Spaces requires port 7860
EXPOSE 7860

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
