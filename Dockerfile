FROM python:3.11-slim

WORKDIR /app

# Prevent Python from writing pyc files and buffering stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as an unprivileged user
RUN useradd --create-home --uid 1000 gabook && chown -R gabook:gabook /app
USER gabook

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request,sys; p=os.environ.get('PORT'); sys.exit(0 if not p else (urllib.request.urlopen('http://127.0.0.1:%s/health' % p, timeout=4).status != 200))"

CMD ["python", "main.py"]
