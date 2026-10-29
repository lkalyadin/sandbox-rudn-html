#!/usr/bin/env python3
"""
Прокси к Vercel AI Gateway для учебного стенда.

Зачем он нужен
--------------
Ключ шлюза НЕ должен лежать внутри песочницы: агент (а значит и студент)
читает /proc/self/environ и достаёт оттуда переменные окружения, а через
urllib (который политикой не запрещён) может пойти напрямую в шлюз любой
моделью — в том числе платной, минуя список моделей в UI и минуя лимит.

Поэтому ключ живёт здесь, в отдельном контейнере, а песочница ходит в шлюз
через этот прокси. Прокси держит настоящий ключ, но наружу отдаёт только
модели из белого списка — все они бесплатны (цена 0 в шлюзе).

Что делает прокси
-----------------
* принимает POST /v1/chat/completions (и /v1/messages — для Anthropic-совместимых
  моделей шлюз идёт по этому пути);
* достаёт поле "model" из тела запроса;
* если модель не в ALLOWED_MODELS — отвечает 403 и НЕ тратит баланс;
* иначе подставляет настоящий ключ и пересылает запрос на ai-gateway.vercel.sh;
* ответ отдаёт как есть, поток (SSE) поддерживается.

Модель в теле запроса — единственный способ выбрать модель в OpenAI-совместимом
API, поэтому фильтрация по нему достаточна: подделать нельзя, поле проверяется
сервером.

Запуск: PORT=8080 ALLOWED_MODELS=... AI_GATEWAY_API_KEY=... python3 proxy.py
"""

import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8080"))
UPSTREAM = "https://ai-gateway.vercel.sh"
API_KEY = os.environ.get("AI_GATEWAY_API_KEY", "")

ALLOWED = {
    m.strip()
    for m in os.environ.get("ALLOWED_MODELS", "").split(",")
    if m.strip()
}

# Тело запроса может быть большим (длинный контекст), но не бесконечным.
MAX_BODY = 8 * 1024 * 1024

# Куда пересылаем. Шлюз принимает и /v1/chat/completions, и /v1/messages.
FORWARD_PATHS = ("/v1/chat/completions", "/v1/messages", "/v1/responses")


def log(msg):
    print(msg, file=sys.stderr, flush=True)


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
                        for m in sorted(ALLOWED)
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

        if not model or model not in ALLOWED:
            log(f"DENY model={model!r} path={self.path}")
            self._send_json(
                403,
                {
                    "error": {
                        "message": (
                            f"Модель {model!r} недоступна на учебном стенде. "
                            "Разрешены только бесплатные модели."
                        ),
                        "type": "invalid_request_error",
                    }
                },
            )
            return

        req = urllib.request.Request(
            UPSTREAM + self.path,
            data=body,
            method="POST",
            headers={
                "Content-Type": self.headers.get("Content-Type", "application/json"),
                "Authorization": f"Bearer {API_KEY}",
                "Accept": self.headers.get("Accept", "text/event-stream"),
            },
        )

        try:
            upstream = urllib.request.urlopen(req, timeout=600)
        except urllib.error.HTTPError as e:
            payload = e.read()
            log(f"UPSTREAM {e.code} model={model!r}")
            self.send_response(e.code)
            self.send_header("Content-Type", e.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        except Exception as e:  # сеть, таймаут и прочее
            log(f"ERROR model={model!r} {e}")
            self._send_json(
                502,
                {"error": {"message": f"gateway proxy error: {e}", "type": "api_error"}},
            )
            return

        ctype = upstream.headers.get("Content-Type", "application/json")
        log(f"ALLOW model={model!r} path={self.path}")
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
    if not API_KEY:
        log("FATAL: AI_GATEWAY_API_KEY не задан")
        sys.exit(1)
    if not ALLOWED:
        log("FATAL: ALLOWED_MODELS пуст")
        sys.exit(1)
    log(f"gateway proxy on :{PORT} allowed={sorted(ALLOWED)}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
