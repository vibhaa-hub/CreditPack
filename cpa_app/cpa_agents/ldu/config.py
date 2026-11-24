"""Runtime mode and LDU service addresses, from the environment.

  CPA_LDU_MODE           inprocess (default) | distributed
  CPA_EXTRACTION_URL     base URL of the document-extraction LDU (distributed mode)
  CPA_ADAPTERS_URL       base URL of the external-adapters LDU (distributed mode)"""
import os


def mode() -> str:
    m = os.getenv("CPA_LDU_MODE", "inprocess")
    if m not in ("inprocess", "distributed"):
        raise ValueError(f"CPA_LDU_MODE must be inprocess or distributed, got {m!r}")
    return m


def distributed() -> bool:
    return mode() == "distributed"


def service_url(ldu: str) -> str:
    var = {"document-extraction": "CPA_EXTRACTION_URL", "external-adapters": "CPA_ADAPTERS_URL"}[ldu]
    url = os.getenv(var)
    if not url:
        raise RuntimeError(f"{var} must be set in distributed mode (the {ldu} LDU's address)")
    return url.rstrip("/")
