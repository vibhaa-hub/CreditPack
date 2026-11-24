# One image for every LDU; the LDU name is the command argument:
#   docker run cpa-app due-diligence-agent
# (see docker-compose.yml, which runs one service per active LDU).

# ---- the React UI bundle ----
FROM node:22-alpine AS ui
WORKDIR /ui
COPY workbench/frontend/package.json workbench/frontend/package-lock.json ./
RUN npm ci
COPY workbench/frontend/ ./
RUN npm run build

# ---- the Python application ----
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    CPA_LDU_HOST=0.0.0.0 CPA_LDU_PORT=8080
WORKDIR /app
# Tesseract: OCR for scanned PDFs and images in the document-extraction LDU. Packages come over
# HTTPS (some networks block plain HTTP to the Debian mirrors). OCR=0 skips it; if the install
# fails the build continues without OCR, and /health on document-extraction reports "ocr": false.
ARG OCR=1
RUN if [ "$OCR" = "1" ]; then \
      sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
      && { apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
           || echo "WARNING: Tesseract not installed - OCR disabled in this image"; } \
      && rm -rf /var/lib/apt/lists/*; \
    fi
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY cpa_agents ./cpa_agents
COPY workbench ./workbench
# fictional demo cases offered on the workbench's New case screen
COPY samples ./samples
COPY --from=ui /ui/dist ./workbench/frontend/dist
RUN useradd --create-home --uid 10001 cpa && mkdir -p cpa_agents/.adk && chown -R cpa cpa_agents/.adk
USER cpa
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"
ENTRYPOINT ["python", "-m", "cpa_agents.ldu"]
CMD ["run", "workbench-api"]
