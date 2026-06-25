FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY blackwatch ./blackwatch
COPY rules ./rules
COPY notifications.yaml ./notifications.yaml

EXPOSE 8000
CMD ["uvicorn", "blackwatch.main:app", "--host", "0.0.0.0", "--port", "8000"]
