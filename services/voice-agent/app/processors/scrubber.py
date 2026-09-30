"""PAN / CVV / expiry scrubbing (defense in depth, not the primary control).

The PaymentGate keeps card entry out of the audio path entirely. This scrubber is the backstop for
a caller who reads card details aloud anyway: it runs right after ASR, and the same rules back the
log filter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PAN_TOKEN = "[REDACTED_PAN]"
CVV_TOKEN = "[REDACTED_CVV]"
EXP_TOKEN = "[REDACTED_EXP]"

NUMBER_WORDS = {
    "zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}
REPEATERS = {"double": 2, "triple": 3}
MONTHS = {"january", "february", "march", "april", "may", "june", "july", "august", "september",
          "october", "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep",
          "sept", "oct", "nov", "dec"}
RUN_SEPARATORS = {"-", ",", "."}

_TOKEN_RE = re.compile(r"[A-Za-z]+|\d+|[^\sA-Za-z\d]")
_LOG_PAN_RE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_CARD_CONTEXT_RE = re.compile(
    r"\b(card\s*(number|no\.?|#)?|credit\s+card|debit\s+card|visa|mastercard|amex|american\s+express|discover)\b",
    re.I,
)
_CVV_RE = re.compile(
    r"\b(cvv2?|cvc2?|cv2|security\s+code|card\s+code|card\s+verification(\s+(code|value|number))?)\b"
    r"(\s*(number|code)?\s*(is|was|of|:|=)?\s*)",
    re.I,
)
_EXP_RE = re.compile(
    r"\b(expir\w*|exp\.?(\s*date)?|valid\s+(thru|through|until))\b(\s*(date)?\s*(is|was|of|on|:|=)?\s*)",
    re.I,
)


@dataclass
class ScrubResult:
    text: str
    hits: int


def luhn_valid(digits: str) -> bool:
    if not digits.isdigit() or not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _tokens(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]


def words_to_digits(text: str) -> str:
    """'four three two one' -> '4321'. Other tokens are kept, separated by spaces."""
    out: list[str] = []
    repeat = 1
    for tok, _, _ in _tokens(text):
        low = tok.lower()
        if low in REPEATERS:
            repeat = REPEATERS[low]
            continue
        if low in NUMBER_WORDS and low != "o":
            out.append(NUMBER_WORDS[low] * repeat)
        elif tok.isdigit():
            out.append(tok[0] * (repeat - 1) + tok if repeat > 1 else tok)
        else:
            out.append(" " + tok + " ")
        repeat = 1
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _digit_runs(text: str) -> list[tuple[int, int, str]]:
    """Find runs of spoken or written digits. Returns (start, end, digits)."""
    toks = _tokens(text)
    runs: list[tuple[int, int, str]] = []
    i = 0
    while i < len(toks):
        tok = toks[i][0]
        low = tok.lower()
        is_digitish = tok.isdigit() or (low in NUMBER_WORDS and low != "o") or low in REPEATERS
        if not is_digitish:
            i += 1
            continue
        start = toks[i][1]
        end = toks[i][2]
        digits = ""
        repeat = 1
        j = i
        while j < len(toks):
            t, _, t_end = toks[j]
            lt = t.lower()
            if t.isdigit():
                digits += (t[0] * (repeat - 1)) + t if repeat > 1 else t
                repeat = 1
            elif lt in NUMBER_WORDS and (lt != "o" or digits):
                digits += NUMBER_WORDS[lt] * repeat
                repeat = 1
            elif lt in REPEATERS:
                repeat = REPEATERS[lt]
            elif t in RUN_SEPARATORS and j + 1 < len(toks) and (
                toks[j + 1][0].isdigit() or toks[j + 1][0].lower() in NUMBER_WORDS
            ):
                pass
            else:
                break
            end = t_end
            j += 1
        if digits:
            runs.append((start, end, digits))
        i = max(j, i + 1)
    return runs


def _redact_after_keyword(text: str, pattern: re.Pattern, token: str, accept) -> tuple[str, int]:
    hits = 0
    out = []
    pos = 0
    for m in pattern.finditer(text):
        if m.start() < pos:
            continue
        tail_start = m.end()
        tail = text[tail_start:tail_start + 40]
        stop = re.search(r"[!?;\n]|\.(\s|$)|\b(and|but|then|cvv|cvc|security|card)\b|\[", tail)
        tail = tail[: stop.start()] if stop else tail
        tail = tail.rstrip()
        if tail and accept(tail):
            out.append(text[pos:tail_start])
            out.append(token)
            pos = tail_start + len(tail)
            hits += 1
    out.append(text[pos:])
    return "".join(out), hits


def _is_cvv_tail(tail: str) -> bool:
    return len(re.sub(r"\D", "", words_to_digits(tail))) in (3, 4)


def _is_expiry_tail(tail: str) -> bool:
    low = tail.lower()
    return bool(re.search(r"\d", tail)) or any(w in MONTHS or w in NUMBER_WORDS
                                               for w in re.findall(r"[a-z]+", low))


def scrub_text(text: str) -> ScrubResult:
    """Redact PAN-like digit runs (13-19 digits, written, spaced, dashed, or spoken),
    digits following card keywords, CVVs, and expiry dates."""
    if not text:
        return ScrubResult(text or "", 0)
    hits = 0
    card_context = bool(_CARD_CONTEXT_RE.search(text))
    pieces = []
    pos = 0
    for start, end, digits in _digit_runs(text):
        pan_like = 13 <= len(digits) <= 19
        card_fragment = card_context and len(digits) >= 8
        if pan_like or card_fragment:
            pieces.append(text[pos:start])
            pieces.append(PAN_TOKEN)
            pos = end
            hits += 1
    pieces.append(text[pos:])
    text = "".join(pieces)

    text, cvv_hits = _redact_after_keyword(text, _CVV_RE, CVV_TOKEN, _is_cvv_tail)
    text, exp_hits = _redact_after_keyword(text, _EXP_RE, EXP_TOKEN, _is_expiry_tail)
    return ScrubResult(text, hits + cvv_hits + exp_hits)


def redact_for_logs(text: str) -> str:
    """Cheap regex backstop for log lines: any 13-19 digit run (with spaces or dashes)."""
    return _LOG_PAN_RE.sub(PAN_TOKEN, text) if text else text


def contains_pan_like(text: str) -> bool:
    """True if the text holds any Luhn-valid 13-19 digit sequence (written or spoken)."""
    for _, _, digits in _digit_runs(text or ""):
        for size in range(13, 20):
            for k in range(0, len(digits) - size + 1):
                if luhn_valid(digits[k:k + size]):
                    return True
    return False


try:
    from pipecat.frames.frames import Frame, InterimTranscriptionFrame, TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

    class TranscriptScrubber(FrameProcessor):
        """Consumes TranscriptionFrame / InterimTranscriptionFrame, emits the same frames with PAN,
        CVV, and expiry redacted (and the raw provider `result` dropped). All other frames pass through.
        `on_hit(count)` is called whenever something is redacted."""

        def __init__(self, on_hit=None, **kwargs):
            super().__init__(**kwargs)
            self._on_hit = on_hit

        async def process_frame(self, frame: Frame, direction: FrameDirection):
            await super().process_frame(frame, direction)
            if isinstance(frame, (TranscriptionFrame, InterimTranscriptionFrame)):
                result = scrub_text(frame.text)
                frame.text = result.text
                frame.result = None
                if result.hits and self._on_hit:
                    await self._on_hit(result.hits)
            await self.push_frame(frame, direction)

except ImportError:  # pragma: no cover - pipecat is always installed in the service venv
    TranscriptScrubber = None  # type: ignore[assignment,misc]
