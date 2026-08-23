#!/usr/bin/env python3
"""Check the external MySQL runtime used by Co-SQLi without printing credentials."""

from __future__ import annotations

import argparse
import sys
import pymysql

from cosqli.synthesis.injection_pipeline import get_mysql_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true", help="Suppress failure details.")
    args = parser.parse_args()

    try:
        config = get_mysql_config()
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
