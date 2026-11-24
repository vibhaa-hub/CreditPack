"""Governed policy parameters (BR-G05). Values come from policy.yaml (or CPA_POLICY_FILE).
Unset values are NOT_CONFIGURED; callers must treat that as a gap, never substitute a default."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_FILE = Path(__file__).resolve().parents[1] / "policy.yaml"


class _NotConfigured:
    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self):
        return "NOT CONFIGURED"

    def __bool__(self):
        return False


NOT_CONFIGURED = _NotConfigured()


@dataclass(frozen=True)
class Policy:
    version: str
    data: dict = field(default_factory=dict)

    def get(self, path: str) -> Any:
        """Dotted lookup, e.g. 'validity_days.sanctions_screening'. Missing or null -> NOT_CONFIGURED."""
        node: Any = self.data
        for part in path.split("."):
            if not isinstance(node, dict) or node.get(part) is None:
                return NOT_CONFIGURED
            node = node[part]
        return node

    def is_set(self, path: str) -> bool:
        return self.get(path) is not NOT_CONFIGURED


def load_policy(path: str | os.PathLike | None = None) -> Policy:
    p = Path(path or os.getenv("CPA_POLICY_FILE") or DEFAULT_FILE)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return Policy(version=str(data.get("version", "unversioned")), data=data)


def from_dict(data: dict) -> Policy:
    """Build a policy in memory (tests, what-if)."""
    return Policy(version=str(data.get("version", "unversioned")), data=data)
