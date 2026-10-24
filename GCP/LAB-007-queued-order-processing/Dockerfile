FROM python:3.12.15-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/app
COPY requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt
COPY app/ /srv/app/
COPY scripts/run-container.py /srv/run-container.py
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["python", "/srv/run-container.py"]
