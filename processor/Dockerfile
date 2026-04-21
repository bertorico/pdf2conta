FROM python:3.12-slim

WORKDIR /app

# Installa poppler-utils per pdf2image
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    poppler-utils && \
    rm -rf /var/lib/apt/lists/*

# Installa dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia script principale
COPY process.py .

CMD ["python", "-u", "process.py"]
