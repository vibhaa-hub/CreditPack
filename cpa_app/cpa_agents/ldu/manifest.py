"""The LDU manifest: which Least Deployable Unit hosts each agent or component.

Loaded from manifest.yaml (override the path with CPA_LDU_MANIFEST). `check_agents` is the
startup check every process runs after building agents: each built agent must be in exactly
one active agent LDU, and every agent the manifest names must exist."""
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).with_name("manifest.yaml")
KINDS = ("agent", "api", "worker", "static")
STATUSES = ("active", "planned")


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Ldu:
    name: str
    kind: str
    status: str
    ast_units: tuple = ()
    agents: tuple = ()
    components: tuple = ()
    parallel: tuple = ()
    concurrency: int = 4
    max_attempts: int = 4
    model: str | None = None

    @property
    def active(self) -> bool:
        return self.status == "active"


@dataclass(frozen=True)
class Manifest:
    version: int
    ldus: dict = field(default_factory=dict)        # name -> Ldu

    def ldu(self, name: str) -> Ldu:
        if name not in self.ldus:
            raise ManifestError(f"unknown LDU: {name}")
        return self.ldus[name]

    def ldu_of(self, agent: str) -> Ldu:
        for u in self.ldus.values():
            if agent in u.agents:
                return u
        raise ManifestError(f"agent {agent} is not assigned to any LDU")

    @property
    def parallel_agents(self) -> frozenset:
        return frozenset(a for u in self.ldus.values() for a in u.parallel)

    @property
    def assigned_agents(self) -> list:
        return [a for u in self.ldus.values() if u.kind == "agent" and u.active for a in u.agents]


def parse(data: dict) -> Manifest:
    if not isinstance(data, dict) or not isinstance(data.get("ldus"), dict):
        raise ManifestError("manifest must have an 'ldus' mapping")
    ldus = {}
    for name, d in data["ldus"].items():
        d = d or {}
        kind, status = d.get("kind"), d.get("status", "active")
        if kind not in KINDS:
            raise ManifestError(f"LDU {name}: kind must be one of {KINDS}, got {kind!r}")
        if status not in STATUSES:
            raise ManifestError(f"LDU {name}: status must be one of {STATUSES}, got {status!r}")
        agents = tuple(d.get("agents") or ())
        if agents and kind != "agent":
            raise ManifestError(f"LDU {name}: only agent LDUs can host agents")
        parallel = tuple(d.get("parallel") or ())
        stray = [a for a in parallel if a not in agents]
        if stray:
            raise ManifestError(f"LDU {name}: parallel agents not hosted here: {', '.join(stray)}")
        conc, attempts = d.get("concurrency", 4), d.get("max_attempts", 4)
        if not isinstance(conc, int) or conc < 1:
            raise ManifestError(f"LDU {name}: concurrency must be a positive integer")
        if not isinstance(attempts, int) or attempts < 1:
            raise ManifestError(f"LDU {name}: max_attempts must be a positive integer")
        ldus[name] = Ldu(name=name, kind=kind, status=status, ast_units=tuple(d.get("ast_units") or ()),
                         agents=agents, components=tuple(d.get("components") or ()), parallel=parallel,
                         concurrency=conc, max_attempts=attempts, model=d.get("model"))
    m = Manifest(version=int(data.get("version", 1)), ldus=ldus)
    seen: dict = {}
    for u in ldus.values():
        for a in u.agents:
            if a in seen:
                raise ManifestError(f"agent {a} is assigned to more than one LDU: {seen[a]}, {u.name}")
            seen[a] = u.name
    return m


def load(path: str | Path | None = None) -> Manifest:
    p = Path(path or os.getenv("CPA_LDU_MANIFEST") or DEFAULT_PATH)
    return parse(yaml.safe_load(p.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def get_manifest() -> Manifest:
    return load()


def check_agents(built: list | set | dict, manifest: Manifest | None = None) -> None:
    """Startup check: raise ManifestError naming every unassigned or unknown agent."""
    m = manifest or get_manifest()
    built = set(built)
    planned = [a for u in m.ldus.values() if not u.active for a in u.agents]
    if planned:
        raise ManifestError(f"agents assigned to a planned LDU: {', '.join(sorted(planned))}")
    assigned = set(m.assigned_agents)
    missing = sorted(built - assigned)
    unknown = sorted(assigned - built)
    problems = []
    if missing:
        problems.append(f"agents not assigned to any LDU: {', '.join(missing)}")
    if unknown:
        problems.append(f"agents in the manifest but not built: {', '.join(unknown)}")
    if problems:
        raise ManifestError("; ".join(problems))
