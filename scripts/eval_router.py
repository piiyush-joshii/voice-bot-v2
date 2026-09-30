"""Report MiniLM router accuracy on tests/data/router_eval.yaml."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "voice-agent"))

from app.config import DATA_DIR  # noqa: E402
from app.processors.router import FAST_PATH_INTENTS, IntentRouter  # noqa: E402
from app.services.embedder import build_embedder  # noqa: E402


def main() -> int:
    cases = yaml.safe_load((ROOT / "tests" / "data" / "router_eval.yaml").read_text())
    router = IntentRouter(
        build_embedder("sentence-transformers/all-MiniLM-L6-v2"),
        DATA_DIR / "intents.yaml",
        DATA_DIR / "faq.yaml",
    )
    correct = 0
    pay_fast = 0
    fast_total = 0
    fast_ok = 0
    misses: list[str] = []
    by_intent: Counter[str] = Counter()
    for case in cases:
        decision = router.route(case["text"], authenticated=True)
        ok = decision.intent == case["intent"]
        correct += int(ok)
        by_intent[case["intent"]] += int(ok)
        if not ok:
            misses.append(f"  {case['text']!r} -> {decision.intent} ({decision.score:.2f}) want {case['intent']}")
        if decision.intent == "pay_bill" and decision.path == "fast":
            pay_fast += 1
        if decision.path == "fast":
            fast_total += 1
            if decision.intent in FAST_PATH_INTENTS and ok:
                fast_ok += 1
    n = len(cases)
    print(f"top-1 accuracy: {correct}/{n} = {correct / n:.1%}")
    print(f"fast-path decisions: {fast_total} (correct fast-path intent: {fast_ok})")
    print(f"pay_bill predicted as fast-path: {pay_fast} (must be 0)")
    if misses:
        print("misses:")
        print("\n".join(misses))
    return 0 if pay_fast == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
