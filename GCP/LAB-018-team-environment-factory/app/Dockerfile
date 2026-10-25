FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /srv/app
COPY --chown=10001:10001 main.py /srv/app/main.py
USER 10001:10001
EXPOSE 8080
CMD ["python", "/srv/app/main.py"]
