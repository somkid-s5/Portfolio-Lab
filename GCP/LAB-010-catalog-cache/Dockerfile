FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

RUN groupadd --gid 10010 lab10 \
    && useradd --uid 10010 --gid 10010 --create-home --shell /usr/sbin/nologin lab10

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r /app/requirements.txt

COPY app/ /app/app/
COPY scripts/ /app/scripts/

USER 10010:10010
EXPOSE 8080
ENTRYPOINT ["python", "-m", "app.entrypoint"]
