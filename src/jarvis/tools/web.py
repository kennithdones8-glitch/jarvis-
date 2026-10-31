"""Web fetch tool.

Fetches public http(s) pages as text. Every hop (including redirects) is checked so the
tool cannot reach this Mac, the local network or cloud metadata endpoints (SSRF). Page text
is returned marked untrusted: it is data for the model, never instructions.

Each hop is resolved once and the connection is pinned to that checked address, so DNS rebinding\ncan't swap in a private one. Only ports 80/443; one overall deadline; at most 5 redirects.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

from ..core.permissions import ResourceKind, Tier
from ..core.tools import ActionSpec, CallContext, ToolError, ToolSpec

MAX_BYTES = 2_000_000
MAX_TEXT_CHARS = 100_000
TEXT_TYPES = ("text/html", "text/plain", "application/json", "application/xhtml+xml", "text/markdown")
USER_AGENT = "JARVIS-personal-assistant/0.3 (+local research tool)"

Resolver = Callable[[str], list[str]]


def system_resolver(host: str) -> list[str]:
    return list({info[4][0] for info in socket.getaddrinfo(host, None)})


ALLOWED_PORTS = frozenset({80, 443})
MAX_REDIRECTS = 5
Connector = Callable[[str, int, float], socket.socket]


def system_connect(ip: str, port: int, timeout: float) -> socket.socket:
    return socket.create_connection((ip, port), timeout=timeout)


def check_public_url(url: str, resolve: Resolver = system_resolver,
                     ports: frozenset[int] = ALLOWED_PORTS) -> tuple[Any, str]:
    """Validate one hop and return (parsed URL, the public IP to connect to). The caller must connect to
    exactly that IP — resolving again would let DNS rebinding swap in a private address."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ToolError("only http(s) URLs with a host are allowed")
    if parts.username or parts.password:
        raise ToolError("URLs with embedded credentials are not allowed")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise ToolError("invalid port in URL") from None
    if port not in ports:
        raise ToolError(f"port {port} is not allowed (web pages only: {', '.join(map(str, sorted(ports)))})")
    try:
        addresses = resolve(parts.hostname)
    except OSError as exc:
        raise ToolError(f"could not resolve {parts.hostname}: {exc}", retryable=True) from None
    if not addresses:
        raise ToolError(f"could not resolve {parts.hostname}", retryable=True)
    for addr in addresses:
        ip = ipaddress.ip_address(addr.split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise ToolError(f"refusing to fetch non-public address {ip} ({parts.hostname})")
    return parts, addresses[0]


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "head"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "pre"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in "".join(self.parts).splitlines())
        return "\n".join(line for line in lines if line)


def html_to_text(html: str) -> tuple[str, str]:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.title.strip(), parser.text()


class WebTool:
    """Fetches public pages over direct connections pinned to the address that passed the check.
    System HTTP proxies are not used (a proxy would do its own DNS lookup, defeating the check)."""

    def __init__(self, *, resolve: Resolver = system_resolver, timeout: float = 20.0,
                 connect: Connector = system_connect, ports: frozenset[int] = ALLOWED_PORTS):
        self.resolve = resolve
        self.timeout = timeout
        self.connect = connect
        self.ports = frozenset(ports)

    def spec(self) -> ToolSpec:
        return ToolSpec("web", "Fetch public web pages as text", {
            "fetch": ActionSpec(Tier.READ, "url", ResourceKind.URL, timeout_s=self.timeout + 5),
        }, self.handle)

    def handle(self, action: str, args: dict[str, Any], ctx: CallContext) -> Any:
        if action != "fetch":
            raise ToolError(f"unknown action {action}")
        return self.fetch(str(ctx.resource))

    def fetch(self, url: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout  # one budget for every hop, redirect and byte read
        current = url
        for hop in range(MAX_REDIRECTS + 1):
            parts, ip = check_public_url(current, self.resolve, self.ports)
            status, headers, raw, truncated = self._get(parts, ip, deadline)
            if status in (301, 302, 303, 307, 308):
                location = headers.get("Location")
                if not location:
                    raise ToolError(f"redirect from {current} has no destination")
                current = urljoin(current, location)
                continue
            if status >= 400:
                raise ToolError(f"HTTP {status} fetching {url}", retryable=status in (429, 502, 503, 504))
            ctype = headers.get_content_type()
            charset = headers.get_content_charset() or "utf-8"
            body = raw.decode(charset, errors="replace")
            title, text = html_to_text(body) if "html" in ctype else ("", body)
            return {"url": url, "final_url": current, "status": status, "content_type": ctype, "title": title,
                    "text": text[:MAX_TEXT_CHARS], "truncated": truncated or len(text) > MAX_TEXT_CHARS,
                    "redirects": hop, "untrusted": True}
        raise ToolError(f"too many redirects (more than {MAX_REDIRECTS})")

    def _get(self, parts: Any, ip: str, deadline: float) -> tuple[int, Any, bytes, bool]:
        def remaining() -> float:
            left = deadline - time.monotonic()
            if left <= 0:
                raise ToolError("timed out fetching the page", retryable=True)
            return left

        https = parts.scheme == "https"
        port = parts.port or (443 if https else 80)
        sock = None
        conn = http.client.HTTPConnection(parts.hostname, port, timeout=remaining())
        try:
            sock = self.connect(ip, port, remaining())  # the validated address — never a fresh lookup
            if https:
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parts.hostname)
            conn.sock = sock
            path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
            conn.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", parts.netloc)
            for name, value in (("User-Agent", USER_AGENT), ("Accept", "text/html,text/plain;q=0.9"),
                                ("Accept-Encoding", "identity"), ("Connection", "close")):
                conn.putheader(name, value)
            conn.endheaders()
            sock.settimeout(remaining())
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308) or resp.status >= 400:
                return resp.status, resp.headers, b"", False
            ctype = resp.headers.get_content_type()
            if ctype not in TEXT_TYPES:
                raise ToolError(f"unsupported content type {ctype}")
            chunks, total = [], 0
            while True:
                sock.settimeout(remaining())
                chunk = resp.read1(min(65536, MAX_BYTES + 1 - total))  # returns what has arrived
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_BYTES:
                    break
            data = b"".join(chunks)
            return resp.status, resp.headers, data[:MAX_BYTES], total > MAX_BYTES
        except ToolError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise ToolError(f"could not fetch {parts.geturl()}: {exc}", retryable=True) from None
        finally:
            conn.close()
            if sock is not None:
                sock.close()
