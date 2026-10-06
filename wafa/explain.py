"""Turn SHAP values into plain-language reasons and suggested retention actions (same rules as web/scorer.js)."""
from __future__ import annotations

import json
import math
from pathlib import Path

REASONS = json.loads((Path(__file__).resolve().parent / "reasons.json").read_text())
BINARY = {k for k, v in REASONS.items() if not k.startswith("_") and any(x[-1] in "01" for x in v if x.startswith(("up", "down")))}


def _fmt_money(v: float) -> str:
    a = abs(v)
    if a >= 100:
        return f"${math.floor(a + 0.5):,}"             # round half up, like JavaScript's Math.round
    c = math.floor(a * 100 + 0.5)                        # cents, rounded half up
    return f"${c // 100}.{c % 100:02d}".rstrip("0").rstrip(".")


def phrase(feature: str, value: float, contribution: float) -> str | None:
    spec = REASONS.get(feature, {})
    key = "up" if contribution > 0 else "down"
    if feature in BINARY:
        key += "1" if value >= 0.5 else "0"
    tpl = spec.get(key)
    if not tpl or (contribution > 0 and value < spec.get("up_min", float("-inf"))):
        return None
    v = int(value) if float(value).is_integer() else math.floor(value * 10 + 0.5) / 10
    return tpl.replace("{v}", str(v)).replace("{m}", _fmt_money(value)).replace("{s}", "" if v == 1 else "s")


def reasons(features: list[str], x, contribs, k: int = 3) -> dict:
    """Top-k reasons pushing risk up, top-k pulling it down, and the matching suggested actions."""
    pairs = [(f, float(x[i]), float(contribs[i])) for i, f in enumerate(features)]
    up = [p for p in sorted(pairs, key=lambda p: -p[2]) if p[2] > 0.02]
    down = [p for p in sorted(pairs, key=lambda p: p[2]) if p[2] < -0.02]

    def pack(items):
        out = []
        for f, v, c in items:
            t = phrase(f, v, c)
            if t:
                out.append({"feature": f, "text": t, "impact": math.floor(c * 1000 + 0.5) / 1000})
            if len(out) == k:
                break
        return out

    risk, keep = pack(up), pack(down)
    actions = []
    for r in risk:
        a = REASONS[r["feature"]].get("action")
        if a and a not in actions:
            actions.append(a)
    return {"risk": risk, "protective": keep, "actions": actions[:2]}
