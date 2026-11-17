FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py db.py ./

# База лежит в /app/data, чтобы её можно было вынести в volume
ENV DB_PATH=/app/data/clients.db
VOLUME ["/app/data"]

CMD ["python", "bot.py"]
