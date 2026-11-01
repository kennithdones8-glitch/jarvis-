"""Dashboard foundations: readable contrast, minimum text size, touch targets, no background animation."""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "server" / "static"
CSS = (STATIC / "app.css").read_text()
JS = (STATIC / "app.js").read_text()


def _lum(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def token(name: str) -> str:
    return re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}})", CSS).group(1)


def test_every_text_colour_meets_wcag_aa_on_page_and_panels():
    page, panel = token("bg"), "#1b1108"  # panel = lightest part of the panel gradient over the page
    for name in ("text", "muted", "faint", "gold", "gold-hi", "red", "arc", "ok"):
        for background in (page, panel):
            assert contrast(token(name), background) >= 4.5, f"--{name} on {background}"


def test_no_text_under_12px():
    sizes = [float(m) for m in re.findall(r"font(?:-size)?:[^;]*?\b(\d+(?:\.\d+)?)px", CSS)]
    assert sizes and min(sizes) >= 12, sorted(sizes)[:5]


def test_touch_targets_are_44px_on_touch_screens_and_inputs_dont_zoom():
    block = CSS.split("@media (pointer: coarse), (max-width: 760px)")[1].split("\n}\n")[0]
    assert ".btn, .tab, .more > summary, .chip, .speak-toggle { min-height: 44px; }" in block
    assert "min-width: 44px" in block and "details > summary { min-height: 44px;" in block
    assert "input, textarea, select { font-size: 16px; min-height: 44px; }" in block


def test_animations_pause_in_the_background_and_respect_reduced_motion():
    assert ".page-hidden *, .page-hidden *::before, .page-hidden *::after { animation-play-state: paused !important; }" in CSS
    assert 'document.addEventListener("visibilitychange", sync)' in JS and 'classList.toggle("page-hidden", document.hidden)' in JS
    assert "@media (prefers-reduced-motion: reduce)" in CSS
