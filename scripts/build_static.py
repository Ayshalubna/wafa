"""Package the dashboard as a static site (no server needed) into dist/static/: python -m scripts.build_static

The dashboard reads web/data/*.json and scores with web/scorer.js, so it runs on any static host. Files are
flattened into one folder for easy upload.
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dist" / "static"
README = """---
title: Wafa — Churn & Retention
emoji: 📉
colorFrom: purple
colorTo: red
sdk: static
app_file: index.html
pinned: true
short_description: Telecom churn risk, SHAP reasons and a retention planner
---

Live demo of [github.com/Ayshalubna/wafa](https://github.com/Ayshalubna/wafa). The XGBoost model and TreeSHAP run in
your browser. Data: IBM Telco Customer Churn sample (Apache 2.0).
"""


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for name in ("app.js", "scorer.js"):
        shutil.copy(ROOT / "web" / name, OUT / name)
    for f in (ROOT / "web" / "fonts").glob("*.woff2"):
        shutil.copy(f, OUT / f.name)
    for f in (ROOT / "web" / "data").glob("*.json"):
        shutil.copy(f, OUT / f.name)
    (OUT / "styles.css").write_text((ROOT / "web" / "styles.css").read_text().replace("url(fonts/", "url("))
    html = (ROOT / "web" / "index.html").read_text().replace('href="fonts/', 'href="')
    html = html.replace('<script src="scorer.js"></script>', '<script>window.WAFA_DATA = "./";</script>\n<script src="scorer.js"></script>')
    assert "WAFA_DATA" in html
    (OUT / "index.html").write_text(html)
    (OUT / "README.md").write_text(README)
    print(f"built {OUT}: {len(list(OUT.iterdir()))} files, {sum(f.stat().st_size for f in OUT.iterdir()) // 1024} KB")


if __name__ == "__main__":
    main()
