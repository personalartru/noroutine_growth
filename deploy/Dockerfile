FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .
COPY build_materials.py .
COPY materials ./materials

ENV POLL_TIMEOUT=25
CMD ["python", "bot.py"]
