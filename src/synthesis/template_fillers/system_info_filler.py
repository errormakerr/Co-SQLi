"""
Fill ``$sysInfo$`` placeholders with MySQL system variables or expressions.
"""

from __future__ import annotations

import re
import random
from typing import Any, Dict, List

import pymysql

from ..random_attributes import GetRandomAttribute


class SystemInformationTemplateFiller:
    """
    Fill ``$sysInfo$`` placeholders with MySQL system variables or expressions.

    Each item in *system_information_list* is expected to have ``variable``
    (the MySQL expression, e.g. ``VERSION()``) and ``type`` (``"integer"`` or
    ``"string"``).
    """

    def __init__(
        self,
        system_information_list: List[Dict[str, Any]],
        mysql_config: Dict[str, Any],
    ):
        self.system_information_list = system_information_list
        self.mysql_config = mysql_config

        self.sysinfo_by_type: Dict[str, List[Dict]] = {
            "integer": [],
            "string": [],
            "all": [],
        }
        self._categorize_system_information()

    def _categorize_system_information(self) -> None:
        """Index system information items by their type."""
        for info in self.system_information_list:
            info_type = info.get("type", "string")
            if info_type == "integer":
                self.sysinfo_by_type["integer"].append(info)
            elif info_type == "string":
                self.sysinfo_by_type["string"].append(info)
            self.sysinfo_by_type["all"].append(info)

    def _query_mysql(self, sql: str) -> str:
        """
        Execute *sql* against MySQL and return the first column of the first row
        as a string.  Returns an empty string on failure.
        """
        connection = None
        try:
            connection = pymysql.connect(
                host=self.mysql_config["host"],
                port=self.mysql_config["port"],
                user=self.mysql_config["user"],
                password=self.mysql_config["password"],
                database=self.mysql_config["database"],
                charset=self.mysql_config.get("charset", "utf8mb4"),
                cursorclass=pymysql.cursors.DictCursor,
            )
            with connection.cursor() as cursor:
                cursor.execute(sql)
                result = cursor.fetchone()
                if result is None:
                    return ""
                if isinstance(result, dict):
                    first_value = next(iter(result.values()), None)
                    return str(first_value) if first_value is not None else ""
                elif isinstance(result, tuple):
                    return str(result[0]) if result[0] is not None else ""
                return str(result)
        except Exception as e:
            print(f"MySQL query failed [{sql}]: {e}")
            return ""
        finally:
            if connection:
                connection.close()

    def _select_sample_for_system_information(self, system_information: str) -> str:
        """
        Retrieve a sample value for *system_information* by executing it as a
        ``SELECT`` query.
        """
        if "SELECT" not in system_information.upper():
            sql = f"SELECT {system_information}"
        else:
            sql = system_information
        return self._query_mysql(sql)

    def _get_random_system_information(self, expected_type: str) -> str:
        """
        Randomly select a system-information variable that matches *expected_type*.

        Falls back to ``"VERSION()"`` (string) or ``"1"`` (integer) when the
        candidate list is empty.
        """
        candidates = self.sysinfo_by_type.get(expected_type, [])
        if not candidates:
            return "VERSION()" if expected_type == "string" else "1"
        return random.choice(candidates)["variable"]

    def fill_template(self, template: Dict[str, Any]) -> str:
        """
        Fill all ``$sysInfo$`` (and other fixed-type) placeholders in *template*.

        Args:
            template: Payload template dict with at least a ``"payload"`` key
                      and an optional ``"expected_types"`` list.

        Returns:
            The fully substituted payload string.
        """
        payload: str = template["payload"]
        expected_types: List[str] = template.get("expected_types", [])

        used_sysinfo: List[str] = []

        # Determine global position of each $sysInfo$ placeholder so we can
        # look up its expected_type by index rather than by relative order.
        # (Relative order would give wrong results when $int$/$character$ etc.
        # appear before $sysInfo$ in the same payload.)
        all_ph_positions = [
            (m.start(), m.group(0))
            for m in re.finditer(r"\$\w+\$", payload)
        ]
        sysinfo_global_indices = [
            idx
            for idx, (_, ph) in enumerate(all_ph_positions)
            if ph == "$sysInfo$"
        ]

        for global_idx in sysinfo_global_indices:
            expected_type = expected_types[global_idx] if global_idx < len(expected_types) else "all"
            sysinfo = self._get_random_system_information(expected_type)
            used_sysinfo.append(sysinfo)
            payload = payload.replace("$sysInfo$", sysinfo, 1)

        # $sample$ — use a value drawn from the last selected sysInfo expression
        if "$sample$" in payload and used_sysinfo:
            sample_value = self._select_sample_for_system_information(used_sysinfo[-1])
            if sample_value and not sample_value.replace(".", "").replace("-", "").isdigit():
                sample_value = f"'{sample_value}'"
            payload = payload.replace("$sample$", sample_value if sample_value else "0")

        # Fixed-type scalar placeholders
        while "$int$" in payload:
            payload = payload.replace("$int$", GetRandomAttribute.random_int_number(), 1)
        while "$float$" in payload:
            payload = payload.replace("$float$", GetRandomAttribute.random_float_number(), 1)
        while "$hex$" in payload:
            payload = payload.replace("$hex$", GetRandomAttribute.random_hex_number(), 1)
        while "$time$" in payload:
            payload = payload.replace("$time$", f"'{GetRandomAttribute.random_time()}'", 1)
        while "$date$" in payload:
            payload = payload.replace("$date$", f"'{GetRandomAttribute.random_date()}'", 1)
        while "$character$" in payload:
            payload = payload.replace("$character$", f"'{GetRandomAttribute.random_character()}'", 1)
        # Legacy format compatibility
        while "#character$" in payload:
            payload = payload.replace("#character$", f"'{GetRandomAttribute.random_character()}'", 1)

        return payload

    def test_connection(self) -> bool:
        """
        Test whether the MySQL connection can be established.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        try:
            connection = pymysql.connect(
                host=self.mysql_config["host"],
                port=self.mysql_config["port"],
                user=self.mysql_config["user"],
                password=self.mysql_config["password"],
                database=self.mysql_config["database"],
                charset=self.mysql_config.get("charset", "utf8mb4"),
            )
            connection.close()
            print(
                f"MySQL connection successful: "
                f"{self.mysql_config['host']}:{self.mysql_config['port']}"
                f"/{self.mysql_config['database']}"
            )
            return True
        except Exception as e:
            print(f"MySQL connection failed: {e}")
            return False
