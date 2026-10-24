FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --requirement /app/requirements.txt
COPY quote_engine /app/quote_engine
USER 10001:10001
EXPOSE 8080 8081
ENTRYPOINT ["python", "-m", "quote_engine"]
CMD ["api"]
