FROM python:3.12-slim-bookworm

USER root
RUN pip install --no-cache-dir flask gunicorn

USER 1000:1000
WORKDIR /app
COPY app.py /app/app.py
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]
