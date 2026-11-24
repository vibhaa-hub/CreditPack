"""BR-D12 / REQ-067: a pack never states or implies a credit decision, a recommendation of
approval or a probability of approval. Pattern-based and deliberately strict: a false positive is
reworded by a human; a false negative would put a decision statement in front of Credit."""
import re

_OUTCOME = r"(approv\w*|grant\w*|sanction\w*|declin\w*|reject\w*|accept\w*)"
_PATTERNS = [
    ("recommendation", rf"\brecommend\w*\b[^.]{{0,60}}?\b{_OUTCOME}"),
    ("recommendation", r"\b(we|i|the preparer|account manager)\s+(fully\s+)?support\w*\s+(the|this)\s+(application|request|proposal|increase)"),
    ("prediction", r"\b(should|will|would|must|can|could|ought to)\s+(certainly\s+|surely\s+|easily\s+)?be\s+(approved|granted|sanctioned|declined|rejected)\b"),
    ("prediction", r"\b(approval|decline|sanction)\s+(is|seems|appears|looks)\s+(very\s+|highly\s+)?(likely|probable|expected|assured|certain|recommended|straightforward)"),
    ("prediction", r"\b(likely|expected|certain|sure)\s+to\s+be\s+(approved|granted|sanctioned|declined|rejected)"),
    ("prediction", r"\b(probability|chance|likelihood|odds)\s+of\s+(approval|being\s+approved|sanction|decline)"),
    ("decision", r"\b(we|i)\s+(hereby\s+)?(approve|decline|reject|sanction|grant)\b"),
    ("decision", r"\b(this|the)\s+(application|request|facility|increase|case|limit)\s+(is|has been|was)\s+(approved|declined|sanctioned|granted|rejected)\b"),
    ("decision", r"(^|[.!?]\s+)(approve|decline|grant|sanction)\s+(the|this)\b"),
    ("decision", r"\b(credit|lending)\s+decision\s*:\s*\w+"),
]
_COMPILED = [(kind, re.compile(p, re.IGNORECASE)) for kind, p in _PATTERNS]


def find_decision_language(text: str) -> list[dict]:
    """Every match with its kind (recommendation, prediction, decision) and the matched words."""
    hits = []
    for kind, rx in _COMPILED:
        for m in rx.finditer(text or ""):
            hits.append({"kind": kind, "text": m.group(0).strip(" .!?")})
    return hits


def has_decision_language(text: str) -> bool:
    return bool(find_decision_language(text))
