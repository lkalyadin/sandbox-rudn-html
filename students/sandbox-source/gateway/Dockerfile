FROM python:3.12-alpine

# Прокси к Vercel AI Gateway. Держит настоящий ключ шлюза (в песочнице его
# нет) и пропускает только модели из белого списка — все они бесплатны.
# См. gateway/proxy.py.

COPY proxy.py /opt/gateway/proxy.py

RUN chmod 0644 /opt/gateway/proxy.py && \
    adduser -D -H -u 65534 proxy 2>/dev/null || true

USER 65534:65534
EXPOSE 8080

ENTRYPOINT ["python3", "/opt/gateway/proxy.py"]
