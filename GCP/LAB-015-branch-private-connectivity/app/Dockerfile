FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /srv
COPY --chown=10001:10001 inventory_api.py /srv/inventory_api.py
USER 10001:10001
EXPOSE 8080
CMD ["python", "/srv/inventory_api.py"]
