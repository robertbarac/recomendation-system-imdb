FROM python:3.12-slim

EXPOSE 80

COPY ./app /app
COPY requirements.txt /app/requirements.txt

WORKDIR /app

RUN python3 -m pip install --no-cache-dir --upgrade setuptools wheel && python3 -m pip install --trusted-host pypi.py.python.org -r requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]