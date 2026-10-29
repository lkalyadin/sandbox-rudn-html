FROM alpine:3.20

# tinyproxy занимает ~1 МБ и умеет ровно то, что нам нужно:
# allowlist доменов плюс журнал заблокированных попыток.
RUN apk add --no-cache tinyproxy

COPY tinyproxy.conf /etc/tinyproxy/tinyproxy.conf
COPY allowlist     /etc/tinyproxy/allowlist
RUN chmod 0644 /etc/tinyproxy/tinyproxy.conf /etc/tinyproxy/allowlist

# Порт прокси. Наружу он НЕ публикуется — доступен только внутри
# docker-сети sandbox_net.
EXPOSE 8888

# -d — не демонизироваться: контейнер должен держать процесс в переднем плане.
ENTRYPOINT ["tinyproxy", "-d", "-c", "/etc/tinyproxy/tinyproxy.conf"]
