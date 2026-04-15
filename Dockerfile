FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    wget gnupg2 unzip curl \
    fonts-liberation libasound2 libatk-bridge2.0-0 \
    libatk1.0-0 libatspi2.0-0 libcups2 libdbus-1-3 \
    libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 \
    libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 \
    libxrandr2 xdg-utils libu2f-udev libvulkan1 \
    && rm -rf /var/lib/apt/lists/*

RUN wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && dpkg -i google-chrome-stable_current_amd64.deb || apt-get -fy install \
    && rm google-chrome-stable_current_amd64.deb

RUN CHROME_MAJOR=$(google-chrome --version | grep -oP '\d+' | head -1) \
    && DRIVER_URL=$(curl -s "https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_$CHROME_MAJOR" || echo "") \
    && if [ -n "$DRIVER_URL" ]; then \
         wget -q "https://storage.googleapis.com/chrome-for-testing-public/$DRIVER_URL/linux64/chromedriver-linux64.zip" -O /tmp/cd.zip \
         && unzip /tmp/cd.zip -d /tmp/ \
         && mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/ \
         && chmod +x /usr/local/bin/chromedriver \
         && rm -rf /tmp/cd*; \
       fi

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/data /app/photos /app/uploads /app/templates /app/static

ENV PYTHONUNBUFFERED=1
ENV CHROME_BIN=/usr/bin/google-chrome-stable

EXPOSE 7860

CMD ["python", "app.py"]