#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import os
import sys

import uvicorn

from app import db
from app.config import get_settings
from app.repository import create_user, get_user_by_username
from app.seed import seed_scenarios


def init_db() -> None:
    db.init_db()
    seed_scenarios()
    print("Database initialized and default scenarios checked.")


def init_admin(args) -> None:
    db.init_db()
    seed_scenarios()
    username = args.username or input("Admin username: ").strip()
    if get_user_by_username(username):
        print(f"User {username!r} already exists.")
        return
    password = args.password or getpass.getpass("Admin password: ")
    if len(password) < 10:
        print("Password must be at least 10 characters.", file=sys.stderr)
        raise SystemExit(2)
    create_user(username, password, "admin")
    print(f"Admin user {username!r} created.")


def serve(args) -> None:
    settings = get_settings()
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Diploma EventLab management")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init-db", help="initialize database and seed default scenarios")
    p_init.set_defaults(func=lambda args: init_db())

    p_admin = sub.add_parser("init-admin", help="create first admin user")
    p_admin.add_argument("--username")
    p_admin.add_argument("--password")
    p_admin.set_defaults(func=init_admin)

    p_serve = sub.add_parser("serve", help="run web application")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", default=8000, type=int)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=serve)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
