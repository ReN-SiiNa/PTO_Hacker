# PTO-Hacker. Single stage: the dependency set is small and there is nothing
# to compile, so a builder stage would add complexity and save nothing.
FROM python:3.12-slim

# Streamlit writes a usage-stats file and a config dir; give it a real HOME.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/app

RUN useradd --create-home --uid 1000 app

WORKDIR /app

# Copy requirements first so a code change does not invalidate the pip layer.
COPY requirements.txt requirements-fares.txt ./
RUN pip install --no-cache-dir -r requirements.txt  && pip install --no-cache-dir -r requirements-fares.txt

COPY . .

# /data is the volume mount point: the database must live OUTSIDE the image,
# or every redeploy would throw the user's plan away.
RUN mkdir -p /data && chown -R app:app /app /data
USER app

ENV PTOHACKER_DB=/data/pto.db

EXPOSE 8501

# Streamlit ships this endpoint; no need to add one.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request as u, sys; \
sys.exit(0 if u.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3).status == 200 else 1)"

# Binding 0.0.0.0 is correct INSIDE the container -- compose controls what is
# actually reachable from the host.
CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
