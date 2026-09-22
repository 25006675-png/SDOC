# SDOC web service. The API serves sdoc-app/ and sdoc-landing/ from the repo
# root, so the whole repository is copied, then the app runs from backend/.
FROM python:3.12-slim

# tesseract lets the extraction recovery step OCR a scanned PDF.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY . .

WORKDIR /app/backend
# Tokens, sync state and attachment copies live here; Render's disk is reset on each deploy.
# Cases imported from the demo folders (not from a mailbox) point at these files, and
# no mailbox can re-download them, so they ship in the image.
# Mailbox cases keep their mailbox path; shipping the copies means the demo
# renders even if the mailbox cannot be reached from the host.
RUN mkdir -p data/attachments \
    && cp demo-data/attachments/*.pdf seed-attachments/*.pdf data/attachments/ \
    && cp -r seed-attachments/gmail data/attachments/
# Render supplies PORT; 10000 is its default when unset.
CMD ["sh", "-c", "uvicorn sdoc.api:app --host 0.0.0.0 --port ${PORT:-10000}"]
