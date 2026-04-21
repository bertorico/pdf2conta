FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    gradio==5.23.0 \
    requests \
    Pillow

COPY app.py .

EXPOSE 7860

CMD ["python", "app.py"]
