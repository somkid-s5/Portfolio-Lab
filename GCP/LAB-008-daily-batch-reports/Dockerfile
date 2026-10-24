FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY requirements.txt /srv/requirements.txt
RUN python -m pip install --no-cache-dir -r /srv/requirements.txt

COPY app/ /srv/app/

USER 10001:10001
CMD ["python", "-m", "app.job"]
