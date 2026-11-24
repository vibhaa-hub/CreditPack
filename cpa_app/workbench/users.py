"""Workbench users: scrypt password hashes with a per-user salt, roles, and a small CLI.

    python -m workbench.users add jsmith --name "Jane Smith" --role account_manager
    python -m workbench.users list
    python -m workbench.users disable jsmith
"""
import argparse
import base64
import getpass
import hashlib
import hmac
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from cpa_agents.store import get_store
from cpa_agents.store.schema import users

from .permissions import ROLES

_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (_N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        got = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(base64.b64decode(dk)))
        return hmac.compare_digest(got, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


def add_user(username: str, display_name: str, roles: list[str], password: str) -> dict:
    bad = [r for r in roles if r not in ROLES]
    if bad or not roles:
        raise ValueError(f"unknown role(s) {bad or roles}; use {sorted(ROLES)}")
    if len(password) < 10:
        raise ValueError("password must be at least 10 characters")
    eng = get_store().engine
    with eng.begin() as c:
        if c.execute(select(users.c.username).where(users.c.username == username)).first():
            raise ValueError(f"user {username} already exists")
        c.execute(users.insert().values(username=username, display_name=display_name, roles=list(roles),
                                        password_hash=hash_password(password), active=True,
                                        created_at=datetime.now(timezone.utc)))
    return {"username": username, "display_name": display_name, "roles": list(roles)}


def get_user(username: str) -> dict | None:
    with get_store().engine.connect() as c:
        r = c.execute(select(users).where(users.c.username == username)).mappings().first()
    return dict(r) if r else None


def authenticate(username: str, password: str) -> dict | None:
    u = get_user(username)
    if not u or not u["active"] or not verify_password(password, u["password_hash"]):
        return None
    return {k: u[k] for k in ("username", "display_name", "roles")}


def list_users() -> list[dict]:
    with get_store().engine.connect() as c:
        rows = c.execute(select(users.c.username, users.c.display_name, users.c.roles, users.c.active)
                         .order_by(users.c.username)).mappings().all()
    return [dict(r) for r in rows]


def set_active(username: str, active: bool) -> None:
    with get_store().engine.begin() as c:
        n = c.execute(users.update().where(users.c.username == username).values(active=active)).rowcount
    if not n:
        raise ValueError(f"no user {username}")


def actor(user: dict, role: str | None = None) -> str:
    """How a user appears in the audit trail (BR-G02)."""
    return f"{user['display_name']} ({user['username']}, {role or '/'.join(user['roles'])})"


def main(argv=None) -> int:
    from dotenv import load_dotenv
    load_dotenv(".env")
    ap = argparse.ArgumentParser(prog="python -m workbench.users")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("username")
    a.add_argument("--name", required=True)
    a.add_argument("--role", action="append", required=True, choices=sorted(ROLES))
    a.add_argument("--password", help="omit to be prompted (avoids shell history)")
    sub.add_parser("list")
    d = sub.add_parser("disable")
    d.add_argument("username")
    args = ap.parse_args(argv)
    if args.cmd == "add":
        pw = args.password or getpass.getpass("password: ")
        print(add_user(args.username, args.name, args.role, pw))
    elif args.cmd == "list":
        for u in list_users():
            print(f"{u['username']:<16} {u['display_name']:<24} {','.join(u['roles']):<40} {'active' if u['active'] else 'disabled'}")
    elif args.cmd == "disable":
        set_active(args.username, False)
        print(f"{args.username} disabled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
