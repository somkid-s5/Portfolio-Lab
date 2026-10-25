FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser
COPY --chown=10001:10001 . /srv

USER 10001:10001
EXPOSE 8080
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
