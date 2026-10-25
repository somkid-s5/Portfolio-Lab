FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

RUN groupadd --gid 10001 lab09 \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin lab09

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r /app/requirements.txt

COPY app/ /app/app/

USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["python", "-m", "app.entrypoint"]
