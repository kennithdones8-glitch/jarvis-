"""Web fetch tool.

Fetches public http(s) pages as text. Every hop (including redirects) is checked so the
tool cannot reach this Mac, the local network or cloud metadata endpoints (SSRF). Page text
is returned marked untrusted: it is data for the model, never instructions.

Residual risk: DNS can change between our check and the connection (rebinding).
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urlsplit

from ..core.permissions import ResourceKind, Tier
from ..core.tools import ActionSpec, CallContext, ToolError, ToolSpec

MAX_BYTES = 2_000_000
MAX_TEXT_CHARS = 100_000
TEXT_TYPES = ("text/html", "text/plain", "application/json", "application/xhtml+xml", "text/markdown")
USER_AGENT = "JARVIS-personal-assistant/0.3 (+local research tool)"

Resolver = Callable[[str], list[str]]


def system_resolver(host: str) -> list[str]:
    return list({info[4][0] for info in socket.getaddrinfo(host, None)})


def check_public_url(url: str, resolve: Resolver = system_resolver) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ToolError("only http(s) URLs with a host are allowed")
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
    def __init__(self, *, resolve: Resolver = system_resolver, timeout: float = 20.0):
        self.resolve = resolve
        self.timeout = timeout

    def spec(self) -> ToolSpec:
        return ToolSpec("web", "Fetch public web pages as text", {
            "fetch": ActionSpec(Tier.READ, "url", ResourceKind.URL, timeout_s=self.timeout + 5),
        }, self.handle)

    def handle(self, action: str, args: dict[str, Any], ctx: CallContext) -> Any:
        if action != "fetch":
            raise ToolError(f"unknown action {action}")
        return self.fetch(str(ctx.resource))

    def fetch(self, url: str) -> dict[str, Any]:
        check_public_url(url, self.resolve)
        tool = self

        class CheckedRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802 (stdlib name)
                check_public_url(newurl, tool.resolve)
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        opener = urllib.request.build_opener(CheckedRedirect)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9"})
        try:
            with opener.open(request, timeout=self.timeout) as resp:
                ctype = resp.headers.get_content_type()
                if ctype not in TEXT_TYPES:
                    raise ToolError(f"unsupported content type {ctype}")
                raw = resp.read(MAX_BYTES + 1)
                charset = resp.headers.get_content_charset() or "utf-8"
                final_url, status = resp.geturl(), resp.status
        except urllib.error.HTTPError as exc:
            raise ToolError(f"HTTP {exc.code} fetching {url}", retryable=exc.code in (429, 502, 503, 504)) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise ToolError(f"could not fetch {url}: {getattr(exc, 'reason', exc)}", retryable=True) from None

        body = raw[:MAX_BYTES].decode(charset, errors="replace")
        title, text = html_to_text(body) if "html" in ctype else ("", body)
        return {"url": url, "final_url": final_url, "status": status, "content_type": ctype, "title": title,
                "text": text[:MAX_TEXT_CHARS], "truncated": len(raw) > MAX_BYTES or len(text) > MAX_TEXT_CHARS,
                "untrusted": True}
