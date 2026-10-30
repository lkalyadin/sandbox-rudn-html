#!/usr/bin/env python3
"""
Прокси к платным моделям для учебного стенда.

Зачем он нужен
--------------
Ключ подписки НЕ должен лежать внутри песочницы: агент (а значит и студент)
читает /proc/self/environ и достаёт оттуда переменные окружения, а через
urllib (который политикой не запрещён) может пойти напрямую к провайдеру любой
моделью — в том числе платной, минуя список моделей в UI и минуя лимит.
Так было с провайдером `go-cheap` 27.10.2026: ключ лежал в config/opencode.json
внутри песочницы и считался скомпрометированным.

Поэтому ключи живут здесь, в отдельном контейнере, а песочница ходит к
провайдерам только через этот прокси. Прокси держит настоящие ключи, но наружу
отдаёт только модели из белых списков.

Поддерживаются два upstream'а (каждый включается своим белым списком):

  * Vercel AI Gateway  — ALLOWED_MODELS        + AI_GATEWAY_API_KEY
    POST https://ai-gateway.vercel.sh/v1/...

  * OpenCode Go        — GO_ALLOWED_MODELS     + OPENCODE_GO_API_KEY
    POST https://opencode.ai/inference/go/openai/v1/...
    (обязателен заголовок x-opencode-session — прокси добавляет его сам)

Модели обоих списков не должны пересекаться: маршрут выбирается по имени модели
в теле запроса. Поле "model" — единственный способ выбрать модель в
OpenAI-совместимом API, подделать его нельзя: прокси проверяет его сам.

Запуск:
  PORT=8080 ALLOWED_MODELS=... AI_GATEWAY_API_KEY=... \
  GO_ALLOWED_MODELS=... OPENCODE_GO_API_KEY=... python3 proxy.py
"""

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8080"))

VERCEL_UPSTREAM = os.environ.get("VERCEL_UPSTREAM", "https://ai-gateway.vercel.sh")
VERCEL_KEY = os.environ.get("AI_GATEWAY_API_KEY", "")

# baseURL уже содержит /v1 — путь запроса /v1/chat/completions превращается в
# /chat/completions.
GO_UPSTREAM = os.environ.get("GO_UPSTREAM", "https://opencode.ai/inference/go/openai/v1")
GO_KEY = os.environ.get("OPENCODE_GO_API_KEY", "")


def _list(name):
    return {m.strip() for m in os.environ.get(name, "").split(",") if m.strip()}


VERCEL_ALLOWED = _list("ALLOWED_MODELS")
GO_ALLOWED = _list("GO_ALLOWED_MODELS")

# Тело запроса может быть большим (длинный контекст), но не бесконечным.
MAX_BODY = 8 * 1024 * 1024

# Куда пересылаем. Шлюз принимает и /v1/chat/completions, и /v1/messages.
FORWARD_PATHS = ("/v1/chat/completions", "/v1/messages", "/v1/responses")


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def route_for(model):
    """Возвращает ('vercel'|'go', upstream, key) или (None, None, None)."""
    if model and model in GO_ALLOWED:
        return "go", GO_UPSTREAM, GO_KEY
    if model and model in VERCEL_ALLOWED:
        return "vercel", VERCEL_UPSTREAM, VERCEL_KEY
    return None, None, None


def upstream_url(kind, path):
    """Собирает адрес upstream'а: у Go в baseURL уже есть /v1."""
    if kind == "go":
        clean = path.split("?")[0]
        clean = clean[3:] if clean.startswith("/v1") else clean
        return GO_UPSTREAM.rstrip("/") + clean
    return VERCEL_UPSTREAM.rstrip("/") + path


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # тишина: заголовки и тела в лог не пишем

    def _send_json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # /v1/models — чтобы OpenCode увидел список разрешённых моделей.
        if self.path.rstrip("/") == "/v1/models":
            self._send_json(
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": m, "object": "model", "owned_by": "vercel"}
                        for m in sorted(VERCEL_ALLOWED)
                    ] + [
                        {"id": m, "object": "model", "owned_by": "opencode-go"}
                        for m in sorted(GO_ALLOWED)
                    ],
                },
            )
            return
        self._send_json(404, {"error": {"message": "not found", "type": "not_found"}})

    def do_POST(self):
        if self.path.split("?")[0] not in FORWARD_PATHS:
            self._send_json(404, {"error": {"message": "not found", "type": "not_found"}})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            self._send_json(413, {"error": {"message": "body too large", "type": "invalid_request_error"}})
            return

        body = self.rfile.read(length) if length else b""

        try:
            model = json.loads(body or b"{}").get("model")
        except Exception:
            model = None

        kind, upstream_base, key = route_for(model)
        if kind is None:
            log(f"DENY model={model!r} path={self.path}")
            self._send_json(
                403,
                {
                    "error": {
                        "message": (
                            f"Модель {model!r} недоступна на учебном стенде. "
                            "Разрешены только модели из списка стенда."
                        ),
                        "type": "invalid_request_error",
                    }
                },
            )
            return

        headers = {
            "Content-Type": self.headers.get("Content-Type", "application/json"),
            "Authorization": f"Bearer {key}",
            "Accept": self.headers.get("Accept", "text/event-stream"),
        }
        # OpenCode Go требует идентификатор сессии для маршрутизации запроса.
        # Клиент передаёт свой, если умеет; иначе подставляем случайный.
        if kind == "go":
            session = self.headers.get("x-opencode-session") or str(uuid.uuid4())
            headers["x-opencode-session"] = session
            headers.setdefault("User-Agent", "opencode-stand-gateway/1.0")

        req = urllib.request.Request(
            upstream_url(kind, self.path),
            data=body,
            method="POST",
            headers=headers,
        )

        try:
            upstream = urllib.request.urlopen(req, timeout=600)
        except urllib.error.HTTPError as e:
            payload = e.read()
            log(f"UPSTREAM {kind} {e.code} model={model!r}")
            self.send_response(e.code)
            self.send_header("Content-Type", e.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        except Exception as e:  # сеть, таймаут и прочее
            log(f"ERROR {kind} model={model!r} {e}")
            self._send_json(
                502,
                {"error": {"message": f"gateway proxy error: {e}", "type": "api_error"}},
            )
            return

        ctype = upstream.headers.get("Content-Type", "application/json")
        log(f"ALLOW {kind} model={model!r} path={self.path}")
        self.send_response(upstream.status)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")

        # Поток (SSE) пробрасываем как есть, чанками.
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            while True:
                chunk = upstream.read(8192)
                if not chunk:
                    break
                self.wfile.write(b"%X\r\n" % len(chunk) + chunk + b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            try:
                upstream.close()
            except Exception:
                pass


if __name__ == "__main__":
    if not VERCEL_ALLOWED and not GO_ALLOWED:
        log("FATAL: ни ALLOWED_MODELS, ни GO_ALLOWED_MODELS не заданы")
        sys.exit(1)
    if VERCEL_ALLOWED and not VERCEL_KEY:
        log("FATAL: ALLOWED_MODELS задан, но AI_GATEWAY_API_KEY пуст")
        sys.exit(1)
    if GO_ALLOWED and not GO_KEY:
        log("FATAL: GO_ALLOWED_MODELS задан, но OPENCODE_GO_API_KEY пуст")
        sys.exit(1)

    overlap = VERCEL_ALLOWED & GO_ALLOWED
    if overlap:
        log(f"FATAL: модель в обоих списках, маршрут неоднозначен: {sorted(overlap)}")
        sys.exit(1)

    log(
        "gateway proxy on :%s vercel=%s go=%s"
        % (PORT, sorted(VERCEL_ALLOWED) or "-", sorted(GO_ALLOWED) or "-")
    )
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
