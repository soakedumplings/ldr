"""Gemini text generation with a resilient fallback chain.

Free-tier Gemini quotas are per-model, so when one model returns 429
(ResourceExhausted) we try the next model in the chain. If every model is
rate-limited we back off and retry the whole chain a couple of times. If the
key is missing or everything still fails, we return None and the caller falls
back to pre-written funny text — the bot never crashes over a quota.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)

# Ordered best -> cheapest. Each has its own quota, so the chain multiplies
# total free capacity. Never use retired gemini-1.5-* models (404).
MODEL_CHAIN = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]

# If the whole chain is exhausted, wait then retry the chain this many times.
_MAX_ROUNDS = 3
_BACKOFF_SECONDS = [5, 20, 60]


class Gemini:
    def __init__(self, api_key: str):
        self._enabled = bool(api_key)
        self._genai = None
        if not self._enabled:
            log.info("No Gemini key set — using pre-written text everywhere.")
            return
        try:
            import google.generativeai as genai

            genai.configure(api_key=api_key)
            self._genai = genai
        except Exception as exc:  # pragma: no cover - import/config guard
            log.warning("Gemini init failed (%s); using pre-written text.", exc)
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def generate(self, prompt: str, *, max_rounds: int = _MAX_ROUNDS) -> str | None:
        """Return generated text, or None if unavailable so caller uses fallback."""
        if not self._enabled or self._genai is None:
            return None

        try:
            from google.api_core.exceptions import ResourceExhausted
        except Exception:  # pragma: no cover
            ResourceExhausted = Exception  # type: ignore

        for round_idx in range(max_rounds):
            exhausted_whole_chain = True
            for model_name in MODEL_CHAIN:
                try:
                    model = self._genai.GenerativeModel(model_name)
                    resp = model.generate_content(prompt)
                    text = (getattr(resp, "text", "") or "").strip()
                    if text:
                        return text
                    # Empty (e.g. safety block): try next model, don't wait.
                    exhausted_whole_chain = False
                except ResourceExhausted:
                    log.info("%s rate-limited (429); trying next model.", model_name)
                    continue  # per-model quota hit -> next model
                except Exception as exc:
                    log.warning("%s failed (%s); trying next model.", model_name, exc)
                    exhausted_whole_chain = False
                    continue

            if not exhausted_whole_chain:
                break  # failures weren't all quota-based; retrying won't help

            # Entire chain was quota-limited: back off and try again later.
            if round_idx < max_rounds - 1:
                wait = _BACKOFF_SECONDS[min(round_idx, len(_BACKOFF_SECONDS) - 1)]
                log.info("Whole chain exhausted; backing off %ss then retrying.", wait)
                time.sleep(wait)

        return None
