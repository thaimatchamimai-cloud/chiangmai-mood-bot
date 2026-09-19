FROM python:3.12-slim

WORKDIR /app
COPY . /app
RUN mkdir -p /app/data

CMD ["python", "bot.py"]

