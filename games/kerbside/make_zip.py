"""Build kerbside-grand-prix.zip: the standalone race (this folder's page and README, plus the game and font files
the JARVIS dashboard serves). Usage: python games/kerbside/make_zip.py [output.zip]"""

import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATIC = HERE.parents[1] / "src" / "jarvis" / "server" / "static"
FILES = {
    "index.html": HERE / "index.html",
    "README.txt": HERE / "README.txt",
    **{n: STATIC / n for n in ("racer-data.js", "racer-career.js", "racer-audio.js", "racer.js", "racer-modes.js", "racer-render.js", "racer-ui.js")},
    "racer.css": STATIC / "racer.css",
    **{f"fonts/{n}": STATIC / "fonts" / n for n in ("rajdhani-500.woff2", "rajdhani-600.woff2", "rajdhani-700.woff2", "OFL-Rajdhani.txt")},
}


def build(out: Path) -> Path:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, src in FILES.items():
            z.write(src, f"kerbside-grand-prix/{name}")
    return out


if __name__ == "__main__":
    print(build(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("kerbside-grand-prix.zip")))
