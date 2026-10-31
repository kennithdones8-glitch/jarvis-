"""Local HTTP servers speaking the Ollama and OpenAI chat-completions wire protocols.

They are protocol test doubles (no real model behind them), used to verify exactly what our
adapters send and how they parse replies, and to prove that blocked requests never arrive.
"""

from __future__ import annotations

import json
import re
import threading
import time
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
                if body.get("stream"):  # like Ollama: one JSON object per line, then a final one with the counts
                    text = fs.reply(body)
                    pieces = [w for w in re.split(r"(\s+)", text) if w]
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-ndjson")
                    self.end_headers()
                    for p in pieces:
                        time.sleep(getattr(fs, "delay", 0))
                        self.wfile.write((json.dumps({"message": {"role": "assistant", "content": p}, "done": False}) + "\n").encode())
                        self.wfile.flush()
                    self.wfile.write((json.dumps({"message": {"role": "assistant", "content": ""}, "done": True,
                                                  "prompt_eval_count": 11, "eval_count": len(pieces)}) + "\n").encode())
                    return
                return self._send(200, {"message": {"role": "assistant", "content": fs.reply(body)},
                                        "prompt_eval_count": 11, "eval_count": 7})
            if kind == "openai" and self.path == "/v1/chat/completions":
                if self.headers.get("Authorization") != f"Bearer {api_key}":
                    return self._send(401, {"error": "bad key"})
                return self._send(200, {"choices": [{"message": {"role": "assistant", "content": fs.reply(body)}}],
                                        "usage": {"prompt_tokens": 1000, "completion_tokens": 500}})
            self._send(404, {})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.handle_error = lambda request, address: None  # a test hanging up mid-reply is expected, not news
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


def start_whisper(text: str = " Hello JARVIS.\n") -> FakeServer:
    """Speaks whisper.cpp's `whisper-server` protocol: POST /inference (multipart, field "file") → {"text": …}.
    Records the form fields and the exact audio bytes it received."""
    import email.parser
    import email.policy

    holder: dict[str, FakeServer] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def do_GET(self) -> None:  # noqa: N802
            fake = holder["s"]
            loading = self.path == "/health" and getattr(fake, "loading", False)
            self.send_response(503 if loading else 200)
            self.send_header("Content-Type", "application/json" if self.path == "/health" else "text/html")
            self.end_headers()
            self.wfile.write(b'{"status":"loading model"}' if loading else
                             b'{"status":"ok"}' if self.path == "/health" else b"<html>whisper.cpp server</html>")

        def do_POST(self) -> None:  # noqa: N802
            fake = holder["s"]
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
                b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + raw)
            fields = {p.get_param("name", header="content-disposition"): p.get_payload(decode=True)
                      for p in msg.iter_parts()}
            fake.received.append({"path": self.path, "fields": {k: v for k, v in fields.items() if k != "file"},
                                  "file": fields.get("file")})
            status = fake.fail_status or 200
            reply = fake.reply({})
            body = json.dumps(reply if isinstance(reply, dict) else {"text": reply}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    fake = FakeServer(url=f"http://127.0.0.1:{server.server_address[1]}", server=server)
    fake.reply = lambda body: text
    holder["s"] = fake
    return fake
