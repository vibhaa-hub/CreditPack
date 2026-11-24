"""Per-LDU model settings, concurrency limit and retry (design D9).

`settings(ldu)` resolves an LDU's model, concurrency and max attempts. In order of precedence:
  CPA_LDU_<NAME>_MODEL / _CONCURRENCY / _MAX_ATTEMPTS   (NAME = LDU name, upper case, '-' -> '_')
  the LDU's entry in manifest.yaml
  the global CPA_MODEL (model only)

`limit(model, ldu)` returns a copy of a model whose calls hold one of the LDU's concurrency slots
and are retried with exponential backoff and jitter on rate-limit, timeout and server errors. Only
a call that has produced no output yet is retried, never a step: tools are not idempotent. The copy
keeps the model's own class as a base, so ADK's model-specific behaviour is unchanged."""
import asyncio
import os
import random
from dataclasses import dataclass, field
from typing import ClassVar

from .manifest import Ldu


def _env(ldu: str, key: str) -> str | None:
    return os.getenv(f"CPA_LDU_{ldu.upper().replace('-', '_')}_{key}") or None


@dataclass
class Settings:
    ldu: str
    model: str | None
    concurrency: int
    max_attempts: int
    base_delay: float = 1.0
    max_delay: float = 30.0


def settings(ldu: Ldu) -> Settings:
    return Settings(ldu=ldu.name,
                    model=_env(ldu.name, "MODEL") or ldu.model,
                    concurrency=int(_env(ldu.name, "CONCURRENCY") or ldu.concurrency),
                    max_attempts=int(_env(ldu.name, "MAX_ATTEMPTS") or ldu.max_attempts),
                    base_delay=float(os.getenv("CPA_MODEL_RETRY_BASE_DELAY", "1.0")),
                    max_delay=float(os.getenv("CPA_MODEL_RETRY_MAX_DELAY", "30.0")))


TRANSIENT_NAMES = ("RateLimit", "Timeout", "ServiceUnavailable", "InternalServer", "APIConnection", "Overloaded")


def transient(e: BaseException) -> bool:
    if isinstance(e, (asyncio.TimeoutError, TimeoutError, ConnectionError)):
        return True
    code = getattr(e, "status_code", None) or getattr(e, "code", None)
    if isinstance(code, int) and (code == 429 or 500 <= code < 600):
        return True
    return any(k in type(e).__name__ for k in TRANSIENT_NAMES)


@dataclass
class Limiter:
    """One LDU's limit in this process (one semaphore per event loop)."""
    s: Settings
    in_flight: int = 0
    peak: int = 0
    retries: int = 0
    _sems: dict = field(default_factory=dict)

    def _sem(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        sem = self._sems.get(id(loop))
        if sem is None:
            sem = self._sems[id(loop)] = asyncio.Semaphore(self.s.concurrency)
        return sem

    def delay(self, attempt: int) -> float:
        d = min(self.s.max_delay, self.s.base_delay * (2 ** (attempt - 1)))
        return d * (0.5 + random.random() / 2)


LIMITERS: dict[str, Limiter] = {}


def limiter(ldu: Ldu) -> Limiter:
    s = settings(ldu)
    cur = LIMITERS.get(ldu.name)
    if cur is None or (cur.s.concurrency, cur.s.max_attempts, cur.s.base_delay) != \
            (s.concurrency, s.max_attempts, s.base_delay):
        cur = LIMITERS[ldu.name] = Limiter(s)
    return cur


class _Limited:
    """Mixin placed before the model's own class: limit and retry around each call."""
    ldu_name: ClassVar[str] = ""

    async def generate_content_async(self, llm_request, stream=False):
        lim = LIMITERS[self.ldu_name]
        attempt = 0
        while True:
            attempt += 1
            yielded = False
            async with lim._sem():
                lim.in_flight += 1
                lim.peak = max(lim.peak, lim.in_flight)
                try:
                    async for r in super().generate_content_async(llm_request, stream):   # type: ignore[misc]
                        yielded = True
                        yield r
                    return
                except Exception as e:
                    if yielded or not transient(e) or attempt >= lim.s.max_attempts:
                        raise
                    lim.retries += 1
                finally:
                    lim.in_flight -= 1
            await asyncio.sleep(lim.delay(attempt))                     # slot released while waiting


_CLASSES: dict[tuple, type] = {}


def _limited_class(base: type, ldu: str) -> type:
    key = (base, ldu)
    if key not in _CLASSES:
        ns = {"__annotations__": {"ldu_name": ClassVar[str]}, "ldu_name": ldu, "__module__": __name__}
        _CLASSES[key] = type(f"{base.__name__}[{ldu}]", (_Limited, base), ns)
    return _CLASSES[key]


def limit(model, ldu: Ldu):
    """A copy of `model` (a BaseLlm, or a model name ADK resolves) limited for `ldu`."""
    from google.adk.models.registry import LLMRegistry
    if isinstance(model, str):
        model = LLMRegistry.new_llm(model)
    limiter(ldu)
    base = type(model)
    while issubclass(base, _Limited):                                   # already limited: re-limit the original
        base = base.__mro__[2]
    m = model.model_copy()
    object.__setattr__(m, "__class__", _limited_class(base, ldu.name))
    return m
