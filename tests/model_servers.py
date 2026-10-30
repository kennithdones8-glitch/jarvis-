"""Local HTTP servers speaking the Ollama and OpenAI chat-completions wire protocols.

They are protocol test doubles (no real model behind them), used to verify exactly what our
adapters send and how they parse replies, and to prove that blocked requests never arrive.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable


@dataclass
class FakeServer:
    url: str
    server: ThreadingHTTPServer
    received: list[dict[str, Any]] = field(default_factory=list)
    reply: Callable[[dict[str, Any]], str] = lambda body: "ok"
    fail_status: int | None = None
    installed: list[str] = field(default_factory=list)

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def all_text(self) -> str:
        return json.dumps(self.received)


def _start(kind: str, api_key: str | None = None) -> FakeServer:
    holder: dict[str, FakeServer] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def _send(self, status: int, body: Any) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            fs = holder["s"]
            if kind == "ollama" and self.path == "/api/tags":
                self._send(200, {"models": [{"name": n, "model": n} for n in fs.installed]})
            else:
                self._send(404, {})

        def do_POST(self) -> None:
            fs = holder["s"]
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            fs.received.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})
            if fs.fail_status:
                return self._send(fs.fail_status, {"error": "simulated"})
            if kind == "ollama" and self.path == "/api/chat":
                return self._send(200, {"message": {"role": "assistant", "content": fs.reply(body)},
                                        "prompt_eval_count": 11, "eval_count": 7})
            if kind == "openai" and self.path == "/v1/chat/completions":
                if self.headers.get("Authorization") != f"Bearer {api_key}":
                    return self._send(401, {"error": "bad key"})
                return self._send(200, {"choices": [{"message": {"role": "assistant", "content": fs.reply(body)}}],
                                        "usage": {"prompt_tokens": 1000, "completion_tokens": 500}})
            self._send(404, {})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    fs = FakeServer(url=base if kind == "ollama" else f"{base}/v1", server=server)
    holder["s"] = fs
    return fs


def start_ollama(installed: list[str]) -> FakeServer:
    fs = _start("ollama")
    fs.installed = installed
    return fs


def start_openai(api_key: str) -> FakeServer:
    return _start("openai", api_key)
