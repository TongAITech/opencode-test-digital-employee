FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY center/requirements.txt /app/center/requirements.txt
RUN pip install --no-cache-dir -r /app/center/requirements.txt

COPY rc8_runtime /app/rc8_runtime
COPY rc8_center /app/rc8_center
COPY center /app/center

EXPOSE 8080

CMD ["uvicorn", "rc8_center.formal_app:app", "--host", "0.0.0.0", "--port", "8080"]
