FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/srv/app PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv/app
COPY app/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin labworker
COPY --chown=10001:10001 app/lab13 ./lab13
USER 10001:10001
ENTRYPOINT ["python", "-m", "lab13.worker"]
