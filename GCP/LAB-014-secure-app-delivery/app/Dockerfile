FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

ARG COMMIT_SHA=unknown
ENV COMMIT_SHA=$COMMIT_SHA

WORKDIR /srv/quote-api
COPY app/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --requirement requirements.txt \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin quoteapi
COPY --chown=10001:10001 app/quote_api.py ./quote_api.py
COPY --chown=10001:10001 tools/verify_quote.py ./tools/verify_quote.py
RUN chown -R 10001:10001 /srv/quote-api

USER 10001:10001
EXPOSE 8080
CMD ["sh", "-c", "exec gunicorn --bind :8080 --workers 1 --threads 8 --timeout 30 --graceful-timeout 10 --access-logfile - --error-logfile - quote_api:app"]
