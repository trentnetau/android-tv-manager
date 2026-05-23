FROM python:3.12-slim-bookworm

# Install ADB — avoid android-sdk-platform-tools (often missing/wrong paths on slim images).
# amd64: official Google platform-tools zip
# arm64 (many Ubuntu Core devices): Debian 'adb' package
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates wget unzip; \
    arch="$(dpkg --print-architecture)"; \
    if [ "$arch" = "amd64" ]; then \
      wget -q https://dl.google.com/android/repository/platform-tools-latest-linux.zip -O /tmp/platform-tools.zip; \
      unzip -q /tmp/platform-tools.zip -d /opt; \
      rm /tmp/platform-tools.zip; \
      ln -sf /opt/platform-tools/adb /usr/local/bin/adb; \
    else \
      apt-get install -y --no-install-recommends adb; \
      ln -sf /usr/bin/adb /usr/local/bin/adb; \
    fi; \
    /usr/local/bin/adb version; \
    apt-get purge -y wget unzip; \
    apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY frontend/dist ./frontend/dist

ENV ADB_PATH=/usr/local/bin/adb
ENV UPLOAD_DIR=/tmp/android-tv-uploads
ENV STATIC_DIR=/app/frontend/dist

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
