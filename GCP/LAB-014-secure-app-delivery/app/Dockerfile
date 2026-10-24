FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/quote-api
COPY app/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --requirement requirements.txt \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin quoteapi
COPY --chown=10001:10001 app/quote_api.py ./quote_api.py

USER 10001:10001
EXPOSE 8080
CMD ["sh", "-c", "exec gunicorn --bind :${PORT:-8080} --workers 1 --threads 8 --timeout 30 --graceful-timeout 10 --access-logfile - --error-logfile - quote_api:app"]
