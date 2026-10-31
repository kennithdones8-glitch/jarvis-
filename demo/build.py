"""Build the JARVIS phone preview: the real dashboard (index.html, app.css, app.js) plus the in-browser
simulation (demo.js, demo.css), as one self-contained HTML file.

    uv run python demo/build.py            → demo/dist/jarvis-demo.html   (for a claude.ai Artifact)
    uv run python demo/build.py --standalone → demo/dist/jarvis-demo-standalone.html (open in any browser)

The real files are copied, never edited, so the preview always shows the current dashboard.
"""

from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "jarvis" / "server" / "static"
HERE = Path(__file__).resolve().parent
TITLE = "JARVIS Mobile Command Center"


def build(standalone: bool = False) -> str:
    index = (STATIC / "index.html").read_text()
    css = (STATIC / "app.css").read_text()
    for font in sorted((STATIC / "fonts").glob("*.woff2")):
        uri = "data:font/woff2;base64," + base64.b64encode(font.read_bytes()).decode()
        css = css.replace(f'url("/static/fonts/{font.name}")', f'url("{uri}")')
    if "/static/fonts/" in css:
        raise SystemExit("a font in app.css wasn't inlined")
    body = re.search(r"<body>(.*)</body>", index, re.S).group(1)
    for script in ("app.js", "demo.js"):
        js = (STATIC if script == "app.js" else HERE).joinpath(script).read_text()
        if "</script" in js:
            raise SystemExit(f"{script} contains </script and can't be inlined")
    parts = [
        f"<title>{TITLE}</title>",
        '<meta name="theme-color" content="#070504">',
        f"<style>\n{css}\n{(HERE / 'demo.css').read_text()}\n</style>",
        body.strip(),
        f"<script>\n{(HERE / 'demo.js').read_text()}\n</script>",
        f"<script>\n{(STATIC / 'app.js').read_text()}\n</script>",
    ]
    page = "\n".join(parts) + "\n"
    if standalone:
        page = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                '</head>\n<body>\n' + page + "</body>\n</html>\n")
    return page


def main() -> None:
    standalone = "--standalone" in sys.argv
    out = HERE / "dist" / ("jarvis-demo-standalone.html" if standalone else "jarvis-demo.html")
    out.parent.mkdir(exist_ok=True)
    out.write_text(build(standalone))
    print(f"{out.relative_to(ROOT)}  ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
