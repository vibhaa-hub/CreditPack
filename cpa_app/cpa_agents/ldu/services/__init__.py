"""API LDUs: document-extraction and external-adapters. Each module has the service code, a
FastAPI app for distributed mode, and a client that calls the code directly in single-process
mode or the service over HTTP in distributed mode."""
import httpx

_clients: dict[str, httpx.Client] = {}


def client(ldu: str) -> httpx.Client:
    """HTTP client for an API LDU (tests replace it with a TestClient on the service app)."""
    from ..config import service_url
    if ldu not in _clients:
        _clients[ldu] = httpx.Client(base_url=service_url(ldu), timeout=60)
    return _clients[ldu]


def set_client(ldu: str, c) -> None:
    if c is None:
        _clients.pop(ldu, None)
    else:
        _clients[ldu] = c
