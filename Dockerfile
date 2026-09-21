# SDOC web service. The API serves sdoc-app/ and sdoc-landing/ from the repo
# root, so the whole repository is copied, then the app runs from Averis1am/.
FROM python:3.12-slim

# tesseract lets the extraction recovery step OCR a scanned PDF.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app
COPY Averis1am/requirements.txt Averis1am/requirements.txt
RUN pip install --no-cache-dir -r Averis1am/requirements.txt
COPY . .

WORKDIR /app/Averis1am
# Tokens, sync state and attachment copies live here; Render's disk is reset on each deploy.
RUN mkdir -p data
# Render supplies PORT; 10000 is its default when unset.
CMD ["sh", "-c", "uvicorn sdoc.api:app --host 0.0.0.0 --port ${PORT:-10000}"]
