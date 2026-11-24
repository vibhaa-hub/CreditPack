"""Inline XBRL (iXBRL) accounts, the format UK companies file at Companies House.

Every figure in an iXBRL file is tagged with a concept (for example `uk-core:TurnoverRevenue`), a
context (the period or date it belongs to, and any breakdown dimension) and its scale and sign. So
the statement can be read without a model: parse the tags, then map concepts to the standard credit
analysis fields. Only the standard library is used."""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

# FRS 102 / FRS 105 concepts (uk-core taxonomy) -> credit analysis field. The first concept found for
# a field wins. Facts that carry a breakdown dimension are never used for a headline field.
CONCEPTS = {
    "turnover": ("TurnoverRevenue", "Revenue"),
    "cost_of_sales": ("CostSales",),
    "gross_profit": ("GrossProfitLoss",),
    "ebit": ("OperatingProfitLoss",),
    "interest_charge": ("InterestPayableSimilarChargesFinanceCosts", "InterestExpense"),
    "net_profit": ("ProfitLoss", "ProfitLossForPeriod"),
    "fixed_assets": ("FixedAssets", "PropertyPlantEquipment"),
    "current_assets": ("CurrentAssets",),
    "current_liabilities": ("CreditorsDueWithinOneYear", "CurrentLiabilities"),
    "long_term_liabilities": ("CreditorsDueAfterOneYear", "NoncurrentLiabilities"),
    "total_borrowings": ("BankBorrowingsOverdrafts", "Borrowings", "LoansBorrowings"),
    "net_worth": ("Equity", "NetAssetsLiabilities"),
    "total_assets": ("TotalAssets", "Assets"),
    "closing_stock": ("Inventories", "Stocks"),
    "closing_cash": ("CashBankOnHand", "CashCashEquivalents"),
    "dividends": ("DividendsPaid", "DividendsPaidOnShares"),
}
NET_CURRENT = ("NetCurrentAssetsLiabilities",)
AUDITED_HINTS = ("Auditor", "AuditOpinion", "IndependentAuditorsReport")
EXEMPT_HINTS = ("AuditExempt", "ExemptionFromAudit", "UnauditedAccounts")
ABSOLUTE = {"cost_of_sales", "interest_charge", "dividends", "current_liabilities", "long_term_liabilities"}


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.contexts: dict[str, dict] = {}
        self.units: dict[str, str] = {}
        self.facts: list[dict] = []
        self.nonnumeric: list[dict] = []
        self._ctx = None
        self._unit = None
        self._field = None          # 'start' | 'end' | 'instant' | 'member' | 'measure'
        self._fact = None           # a fact being read: {'attrs':…, 'text':[…], 'numeric':bool, 'depth':n}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        t = tag.lower()
        if self._fact is not None:
            self._fact["depth"] += 1
        if t == "xbrli:context":
            self._ctx = {"id": a.get("id"), "dims": []}
        elif self._ctx is not None and t in ("xbrli:startdate", "xbrli:enddate", "xbrli:instant"):
            self._field = t.split(":")[1]
        elif self._ctx is not None and t in ("xbrldi:explicitmember", "xbrldi:typedmember"):
            self._field = "member"
            self._ctx["dims"].append({"dimension": (a.get("dimension") or "").split(":")[-1], "member": ""})
        elif t == "xbrli:unit":
            self._unit = a.get("id")
        elif self._unit and t == "xbrli:measure":
            self._field = "measure"
        elif t in ("ix:nonfraction", "ix:nonnumeric") and self._fact is None:
            self._fact = {"attrs": a, "text": [], "numeric": t == "ix:nonfraction", "depth": 0}

    def handle_endtag(self, tag):
        t = tag.lower()
        if self._fact is not None:
            if self._fact["depth"] == 0 and t in ("ix:nonfraction", "ix:nonnumeric"):
                self._finish_fact()
                return
            self._fact["depth"] -= 1
        if t == "xbrli:context" and self._ctx:
            self.contexts[self._ctx["id"]] = self._ctx
            self._ctx = None
        elif t == "xbrli:unit":
            self._unit = None
        if t in ("xbrli:startdate", "xbrli:enddate", "xbrli:instant", "xbrldi:explicitmember",
                 "xbrldi:typedmember", "xbrli:measure"):
            self._field = None

    def handle_data(self, data):
        if self._fact is not None:
            self._fact["text"].append(data)
        elif self._ctx is not None and self._field in ("startdate", "enddate", "instant"):
            self._ctx[self._field] = data.strip()
        elif self._ctx is not None and self._field == "member" and self._ctx["dims"]:
            self._ctx["dims"][-1]["member"] += data.strip().split(":")[-1]
        elif self._unit and self._field == "measure":
            self.units[self._unit] = data.strip().split(":")[-1]

    def _finish_fact(self):
        f, self._fact = self._fact, None
        a = f["attrs"]
        name = (a.get("name") or "").split(":")[-1]
        text = "".join(f["text"]).strip()
        if not f["numeric"]:
            self.nonnumeric.append({"concept": name, "context": a.get("contextref"), "text": text[:200]})
            return
        value = _number(text, a.get("format") or "", a.get("scale"), a.get("sign"))
        if value is not None:
            self.facts.append({"concept": name, "context": a.get("contextref"), "unit": a.get("unitref"),
                               "value": value, "decimals": a.get("decimals"), "text": text})


def _number(text: str, fmt: str, scale_attr, sign) -> Decimal | None:
    t = text.strip()
    if "zerodash" in fmt or "fixed-zero" in fmt or t in ("-", "–", "—", ""):
        v = Decimal(0)
    else:
        t = t.replace(" ", "").replace(" ", "")
        if "numcommadecimal" in fmt or "num-comma-decimal" in fmt:
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
        try:
            v = Decimal(t)
        except InvalidOperation:
            return None
    if scale_attr:
        v = v.scaleb(int(scale_attr))
    return -v if sign == "-" else v


def parse(data: bytes) -> dict:
    p = _Parser()
    p.feed(data.decode("utf-8", errors="replace"))
    facts = []
    for f in p.facts:
        c = p.contexts.get(f["context"]) or {}
        facts.append({**f, "value": float(f["value"]) if f["value"] != int(f["value"]) else int(f["value"]),
                      "end": c.get("enddate") or c.get("instant"), "start": c.get("startdate"),
                      "instant": "instant" in c, "dimensional": bool(c.get("dims")), "dims": c.get("dims") or [],
                      "currency": p.units.get(f.get("unit") or "", None)})
    names = " ".join(n["concept"] for n in p.nonnumeric)
    if any(h in names for h in EXEMPT_HINTS):
        audit = "unaudited_accounts"
    elif any(h in names for h in AUDITED_HINTS):
        audit = "audited"
    else:
        audit = None
    entity = next((n["text"] for n in p.nonnumeric if "EntityCurrentLegalOrRegisteredName" in n["concept"]), None)
    return {"facts": facts, "audit_basis": audit, "entity_name": entity,
            "periods": sorted({f["end"] for f in facts if f["end"]})}


def statements(parsed: dict) -> list[dict]:
    """One statement per period end with the mapped fields and, for each, the fact it came from."""
    facts = [f for f in parsed["facts"] if not f["dimensional"] and f["end"]]
    by_end_dims: dict[str, list[dict]] = {}
    for f in parsed["facts"]:
        if f["dimensional"] and f["end"]:
            by_end_dims.setdefault(f["end"], []).append(f)
    by_end: dict[str, list[dict]] = {}
    for f in facts:
        by_end.setdefault(f["end"], []).append(f)
    ends = sorted(by_end)
    out = []
    for end in ends:
        fs = by_end[end]
        figures, refs = {}, {}
        for field, concepts in CONCEPTS.items():
            for c in concepts:
                hit = next((f for f in fs if f["concept"] == c), None)
                if hit:
                    v = abs(hit["value"]) if field in ABSOLUTE else hit["value"]
                    figures[field], refs[field] = v, f"ixbrl:{c}@{hit['context']}"
                    break
        # creditors are filed with a maturity dimension (within / after one year)
        for f in by_end_dims.get(end, []):
            if f["concept"] == "Creditors" and len(f["dims"]) == 1                     and f["dims"][0]["dimension"] == "MaturitiesOrExpirationPeriodsDimension":
                field = {"WithinOneYear": "current_liabilities", "AfterOneYear": "long_term_liabilities"}.get(
                    f["dims"][0]["member"])
                if field and field not in figures:
                    figures[field], refs[field] = abs(f["value"]), f"ixbrl:Creditors[{f['dims'][0]['member']}]@{f['context']}"
        if "current_liabilities" not in figures and "current_assets" in figures:
            nca = next((f for f in fs if f["concept"] in NET_CURRENT), None)
            if nca:
                figures["current_liabilities"] = figures["current_assets"] - nca["value"]
                refs["current_liabilities"] = (f"derived: current assets - ixbrl:{nca['concept']}@{nca['context']}")
        prior = _prior_end(end, ends)
        if prior:
            pf = {f["concept"]: f for f in by_end[prior] if f["instant"]}
            for opening, concepts in (("opening_stock", CONCEPTS["closing_stock"]), ("opening_cash", CONCEPTS["closing_cash"])):
                hit = next((pf[c] for c in concepts if c in pf), None)
                if hit:
                    figures[opening], refs[opening] = hit["value"], f"ixbrl:{hit['concept']}@{hit['context']}"
        months = None
        dur = next((f for f in fs if f["start"]), None)
        if dur:
            s, e = date.fromisoformat(dur["start"]), date.fromisoformat(end)
            months = round(((e - s).days + 1) / 30.44)
        if figures:
            cur = next((f["currency"] for f in fs if f.get("currency")), None)
            out.append({"period_end": end, "period_months": months or 12, "currency": cur or "GBP",
                        "figures": figures, "refs": refs})
    # a period that only holds the prior-year comparatives used for opening balances is still a period
    return out


def _prior_end(end: str, ends: list[str]) -> str | None:
    e = date.fromisoformat(end)
    target = date(e.year - 1, e.month, e.day) if not (e.month == 2 and e.day == 29) else e - timedelta(days=366)
    return next((x for x in ends if abs((date.fromisoformat(x) - target).days) <= 7), None)
