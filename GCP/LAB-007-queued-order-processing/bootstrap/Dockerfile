FROM python:3.12.15-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/bootstrap
COPY bootstrap/requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt
COPY bootstrap/installer.py bootstrap/run.py /srv/bootstrap/
COPY sql/schema.sql sql/roles.sql /srv/sql/
COPY app/order_domain.py /srv/app/order_domain.py
USER 10001:10001
ENTRYPOINT ["python", "/srv/bootstrap/run.py"]
