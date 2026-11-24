"""external-adapters LDU (DU-03/04/11, design D8): every call to an external data source goes
through here, with a per-provider rate limit. Today each provider is a STUB backed by
cpa_agents/stubs/*.json; a real adapter replaces one function here, nowhere else.

  CPA_ADAPTER_<PROVIDER>_RATE   requests per second for one provider (default 10). Requests over
                                the limit wait for a token instead of reaching the provider."""
import asyncio
import json
import os
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from ..config import distributed

STUBS = Path(__file__).resolve().parents[2] / "stubs"


def _stub(name: str) -> dict:
    p = STUBS / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


# ---------- providers (STUB implementations) ----------
def companies_house(registered_number: str) -> dict:
    return {"record": _stub("companies_house").get(registered_number), "stub": True}


def sanctions(party: str) -> dict:
    data = _stub("screening")
    return {"result": data.get("sanctions", {}).get(party.strip().upper(), "clear"),
            "list_version": data.get("sanctions_list_version", "STUB"), "stub": True}


def adverse_media(party: str) -> dict:
    data = _stub("screening")
    return {"result": data.get("adverse_media", {}).get(party.strip().upper(), "clear"),
            "sources_searched": ["STUB news index"], "stub": True}


def credit_reference(registered_number: str) -> dict:
    return {"record": _stub("screening").get("credit_reference", {}).get(registered_number or ""), "stub": True}


PROVIDERS = {"companies_house": companies_house, "sanctions": sanctions, "adverse_media": adverse_media,
             "credit_reference": credit_reference}


# ---------- per-provider rate limit ----------
class TokenBucket:
    """`rate` tokens per second, up to `burst` saved. `reserve()` takes a token and returns how long
    the caller must wait before using it (0 when one was available)."""

    def __init__(self, rate: float, burst: float | None = None, clock=time.monotonic):
        self.rate, self.burst, self.clock = rate, burst or max(1.0, rate), clock
        self.tokens, self.at = self.burst, clock()
        self.lock = threading.Lock()
        self.waited = 0

    def reserve(self) -> float:
        with self.lock:
            now = self.clock()
            self.tokens = min(self.burst, self.tokens + (now - self.at) * self.rate)
            self.at = now
            self.tokens -= 1
            wait = 0.0 if self.tokens >= 0 else -self.tokens / self.rate
            if wait:
                self.waited += 1
            return wait

    def acquire(self):
        w = self.reserve()
        if w:
            time.sleep(w)

    async def acquire_async(self):
        w = self.reserve()
        if w:
            await asyncio.sleep(w)


BUCKETS: dict[str, TokenBucket] = {}


def bucket(provider: str) -> TokenBucket:
    if provider not in BUCKETS:
        BUCKETS[provider] = TokenBucket(float(os.getenv(f"CPA_ADAPTER_{provider.upper()}_RATE", "10")))
    return BUCKETS[provider]


def _check(provider: str):
    if provider not in PROVIDERS:
        raise KeyError(f"unknown provider {provider}")


# ---------- client ----------
def lookup(provider: str, **params) -> dict:
    """Client: one external lookup through the external-adapters LDU."""
    _check(provider)
    if not distributed():
        bucket(provider).acquire()
        return PROVIDERS[provider](**params)
    from . import client
    r = client("external-adapters").post(f"/lookup/{provider}", json=params)
    r.raise_for_status()
    return r.json()


def create_service() -> FastAPI:
    app = FastAPI(title="external-adapters")

    @app.get("/health")
    def health():
        return {"ldu": "external-adapters", "ok": True, "providers": sorted(PROVIDERS)}

    @app.post("/lookup/{provider}")
    async def lookup_endpoint(provider: str, params: dict):
        if provider not in PROVIDERS:
            return JSONResponse({"error": f"unknown provider {provider}"}, status_code=404)
        await bucket(provider).acquire_async()
        return PROVIDERS[provider](**params)

    return app
