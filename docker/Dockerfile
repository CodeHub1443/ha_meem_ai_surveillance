FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04

WORKDIR /app

COPY requirements/base.txt .
RUN pip install --no-cache-dir -r base.txt

COPY . .

CMD ["python", "apps/entry_pipeline/main.py"]
