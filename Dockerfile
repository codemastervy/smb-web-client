# ---------------------------------------------------------------------------
# Stage 1: build the SPA
# ---------------------------------------------------------------------------
FROM node:20-bookworm-slim AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY frontend/ ./
RUN npm run build


# ---------------------------------------------------------------------------
# Stage 2: runtime
#
# Runs as a NON-ROOT user. This app is a pure SMB client -- smbprotocol speaks
# SMB2/3 in Python over an ordinary outbound TCP socket, so there is no daemon
# to bind a privileged port and nothing here needs root.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend /build/dist ./frontend

# uid 10001: high, fixed, and outside the range a host is likely to use, so
# the mounted /data ends up owned by something predictable.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin smbweb \
    && mkdir -p /data \
    && chown -R smbweb:smbweb /app /data

ENV FRONTEND_DIR=/app/frontend \
    DATA_DIR=/data

USER smbweb

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health', \
        timeout=4).status == 200 else 1)"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
