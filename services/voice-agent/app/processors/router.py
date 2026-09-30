"""MiniLM intent router: nearest-example cosine similarity over data/intents.yaml, plus FAQ retrieval."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from app.services.embedder import Embedder

FAST_PATH_INTENTS = {"request_agent", "greeting", "goodbye", "bill_due_date", "check_balance"}
AUTH_REQUIRED_FAST_PATH = {"bill_due_date", "check_balance"}


@dataclass
class RouteDecision:
    intent: str
    score: float
    path: str  # "fast" | "llm"
    faq: str | None
    router_ms: float


class IntentRouter:
    def __init__(self, embedder: Embedder, intents_path: Path, faq_path: Path | None,
                 high: float = 0.80, faq_threshold: float = 0.60):
        self._embedder = embedder
        self.high = high
        self.faq_threshold = faq_threshold
        intents = yaml.safe_load(intents_path.read_text())
        self._labels: list[str] = []
        examples: list[str] = []
        for intent, utterances in intents.items():
            for u in utterances:
                self._labels.append(intent)
                examples.append(u)
        self._example_vecs = embedder.embed(examples)
        self._faq: dict[str, str] = {}
        if faq_path and faq_path.exists():
            self._faq = yaml.safe_load(faq_path.read_text()) or {}

    @property
    def intents(self) -> set[str]:
        return set(self._labels)

    def classify(self, text: str) -> tuple[str, float]:
        vec = self._embedder.embed([text])[0]
        sims = self._example_vecs @ vec
        idx = int(np.argmax(sims))
        return self._labels[idx], float(sims[idx])

    def route(self, text: str, authenticated: bool) -> RouteDecision:
        t0 = time.perf_counter()
        intent, score = self.classify(text)
        path = "llm"
        if score >= self.high and intent in FAST_PATH_INTENTS:
            if intent not in AUTH_REQUIRED_FAST_PATH or authenticated:
                path = "fast"
        faq = None
        if intent.startswith("faq_") and score >= self.faq_threshold and intent in self._faq:
            faq = self._faq[intent]
        return RouteDecision(intent, round(score, 3), path, faq, (time.perf_counter() - t0) * 1000)
