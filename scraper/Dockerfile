# MTGGoldfish scraper for a Cloud Run Job. Google Chrome ships for amd64 only,
# which is what Cloud Run runs; build with Cloud Build (see deploy.sh) or
# `docker build --platform linux/amd64`.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Chrome from Google's apt repository, plus Xvfb: UC mode runs headed inside a
# virtual display, which Cloudflare challenges less than headless Chrome.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg xvfb fonts-liberation \
    && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && apt-get purge -y gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt \
    # Fetch the chromedriver matching the installed Chrome now, not on every run.
    && seleniumbase get chromedriver

COPY mtgmeta ./mtgmeta

# Firestore credentials come from the job's service account.
ENTRYPOINT ["python", "-m", "mtgmeta"]
