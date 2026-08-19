#!/usr/bin/env python3
"""Check the local MySQL service used by SQLI without printing credentials."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pymysql
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "database_connection.yaml"


def load_connection_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file) or {}

    required_keys = {"host", "port", "user", "password", "charset"}
    missing_keys = required_keys.difference(config)
    if missing_keys:
        raise ValueError(
            f"{CONFIG_PATH} is missing required keys: {', '.join(sorted(missing_keys))}"
        )
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true", help="Suppress failure details.")
    args = parser.parse_args()

    try:
        config = load_connection_config()
        connection = pymysql.connect(
            host=config["host"],
            port=int(config["port"]),
            user=config["user"],
            password=config["password"],
            charset=config["charset"],
            connect_timeout=2,
            read_timeout=5,
            write_timeout=5,
        )
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM california_schools.schools")
                school_count = cursor.fetchone()[0]
        print(f"MySQL ready; california_schools.schools rows={school_count}")
        return 0
    except Exception as error:
        if not args.quiet:
            print(f"MySQL validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
