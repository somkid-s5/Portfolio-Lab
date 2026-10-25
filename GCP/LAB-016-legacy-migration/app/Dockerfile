FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --requirement requirements.txt
COPY main.py schema.sql seed.sql ./
USER 10001:10001
EXPOSE 8080
CMD ["python", "main.py"]
