"""
SQL injection sample generation pipeline.

This module provides:
- ``SymbolChecker``                 — bracket/quote balance validation
- ``GetRandomAttribute``            — random value generators for placeholder substitution
- ``SpecificDatabaseTemplateFiller``— fills ``$table_N$`` / ``$column_tN_M$`` / ``$sample_tN_M$``
                                       placeholders using a real MySQL database schema
- ``SystemInformationTemplateFiller``— fills ``$sysInfo$`` placeholders with MySQL system
                                        variables / expressions
- ``pipeline``                      — end-to-end function that converts a raw SQL example +
                                       payload template into a labelled injection SQL sample
- ``batch_generate_injection_sqls`` — convenience wrapper around ``pipeline``

Module-level singletons
-----------------------
``gpt_config``, ``gpt``, and ``checker`` are instantiated at import time from the
project's ``config/gpt_config.yaml`` and ``config/database_connection.yaml`` files.
They are shared across all calls to ``pipeline`` within a single process.
"""

from __future__ import annotations

import re
import random
import string
from datetime import date, time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pymysql

from utils.yaml_operation import load_yaml_to_dict
from utils.LLM import LLM
from utils.j2_operation import load_prompt_template


# ---------------------------------------------------------------------------
# Symbol balance checker
# ---------------------------------------------------------------------------

class SymbolChecker:
    """
    Validate bracket and quote balance in a SQL string.

    Single quotes that are intentionally unbalanced (i.e., the SQL-injection
    quote-escaping trick) are **not** flagged here — callers should pass only
    the fragment before any ``--`` comment terminator.
    """

    def __init__(self):
        self.bracket_pairs = {"(": ")", "[": "]", "{": "}"}
        self.quote_symbols = ["'", '"', "`"]

    def check_balanced(self, text: str):
        """
        Check whether all brackets and quotes in *text* are balanced.

        Args:
            text: The SQL fragment to check.

        Returns:
            A ``(bool, message)`` tuple where ``bool`` is ``True`` when the
            text is balanced and ``message`` describes any imbalance found.
        """
        if not isinstance(text, str):
            return False, "Input is not a string"

        stack = []
        quote_stack = []
        i = 0

        while i < len(text):
            char = text[i]

            # Skip escaped characters
            if i > 0 and text[i - 1] == "\\":
                i += 1
                continue

            # Inside a quoted string — only watch for its closing quote
            if quote_stack:
                if char == quote_stack[-1]:
                    quote_stack.pop()
                i += 1
                continue

            # Quotes
            if char in self.quote_symbols:
                quote_stack.append(char)
            # Opening brackets
            elif char in self.bracket_pairs:
                stack.append(char)
            # Closing brackets
            elif char in self.bracket_pairs.values():
                if not stack:
                    return False, f"Position {i}: unexpected closing symbol '{char}'"
                last_open = stack.pop()
                if self.bracket_pairs[last_open] != char:
                    return False, f"Position {i}: mismatched symbols '{last_open}' and '{char}'"

            i += 1

        errors = []
        if stack:
            errors.append(f"Unclosed brackets: {stack}")
        if quote_stack:
            errors.append(f"Unclosed quotes: {quote_stack}")

        if errors:
            return False, "; ".join(errors)
        return True, "All symbols are correctly balanced"


# ---------------------------------------------------------------------------
# Random value generators for fixed-type placeholders
# ---------------------------------------------------------------------------

class GetRandomAttribute:
    """Static helpers that generate random scalar values for SQL placeholders."""

    @staticmethod
    def random_time() -> str:
        """Return a random time string in ``HH:MM:SS`` format."""
        hour = random.randint(0, 23)
        minute = random.randint(0, 59)
        second = random.randint(0, 59)
        return f"{hour:02d}:{minute:02d}:{second:02d}"

    @staticmethod
    def random_date(
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> str:
        """
        Return a random date string in ``YYYY-MM-DD`` format.

        Args:
            start_date: Earliest possible date (default: 2000-01-01).
            end_date:   Latest possible date  (default: 2025-12-31).

        Raises:
            ValueError: If *start_date* is later than *end_date*.
        """
        if start_date is None:
            start_date = date(2000, 1, 1)
        if end_date is None:
            end_date = date(2025, 12, 31)
        if start_date > end_date:
            raise ValueError("start_date must not be later than end_date")
        delta = end_date - start_date
        return (start_date + timedelta(days=random.randint(0, delta.days))).strftime("%Y-%m-%d")

    @staticmethod
    def random_hex_number() -> str:
        """Return a random hex literal string (e.g. ``0x1a2b3c``)."""
        return hex(random.randint(0, 0xFFFFFFFF))

    @staticmethod
    def random_int_number(min_value: int = 0, max_value: int = 100) -> str:
        """Return a random integer as a string."""
        return str(random.randint(min_value, max_value))

    @staticmethod
    def random_float_number(
        min_value: float = 0.0,
        max_value: float = 10.0,
        ndigits: int = 2,
    ) -> str:
        """Return a random float as a string rounded to *ndigits* decimal places."""
        return str(round(random.uniform(min_value, max_value), ndigits))

    @staticmethod
    def random_character() -> str:
        """Return a random ASCII letter."""
        return random.choice(string.ascii_letters)


# ---------------------------------------------------------------------------
# Specific-database template filler
# ---------------------------------------------------------------------------

class SpecificDatabaseTemplateFiller:
    """
    Fill ``$table_N$``, ``$column_tN_M$``, and ``$sample_tN_M$`` placeholders
    by querying a real MySQL schema and sampling actual table/column/value data.

    The ``TYPE_MAPPING`` dict maps the abstract type names used in
    ``expected_types`` to the concrete MySQL column data-type prefixes that
    satisfy each type constraint.
    """

    TYPE_MAPPING: Dict[str, Optional[List[str]]] = {
        "number": ["int", "integer", "bigint", "smallint", "tinyint",
                   "real", "float", "double", "numeric", "decimal"],
        # "integer" shares the same column types as "number"
        # (the inferrer or payloads.json may annotate $sysInfo$ as "integer")
        "integer": ["int", "integer", "bigint", "smallint", "tinyint",
                    "real", "float", "double", "numeric", "decimal"],
        "float": ["real", "float", "double", "numeric", "decimal"],
        "string": ["varchar", "char", "text", "nvarchar", "nchar",
                   "clob", "blob", "string"],
        "date": ["date", "datetime", "timestamp", "time"],
        "time": ["time", "datetime", "timestamp"],
        # "hex" can map to any column type — it replaces a literal value
        "hex": None,
        "character": ["varchar", "char", "text", "nvarchar", "nchar"],
        "boolean": ["bool", "boolean", "bit"],
        "all": None,  # None means no restriction
    }

    def __init__(self, db_schema: Dict, mysql_config: Dict[str, Any]):
        """
        Args:
            db_schema:    Database schema dict (as stored in ``schema.json``).
            mysql_config: MySQL connection parameters (host, port, user, password,
                          database, charset).

        Raises:
            ValueError: If *mysql_config* is ``None``.
        """
        if mysql_config is None:
            raise ValueError("mysql_config must be provided")

        self.db_schema = db_schema
        self.db_name = db_schema.get("database_name", "unknown")
        self.mysql_config = mysql_config

        # Pre-build table info index
        self.tables_info: Dict[str, Dict] = {}
        self.table_names: List[str] = []

        for table in db_schema.get("tables", []):
            table_name = table["table_name"]
            self.table_names.append(table_name)
            columns = []
            column_types = {}
            for col in table.get("columns", []):
                col_name = col["column_name"]
                columns.append(col_name)
                column_types[col_name] = col["data_type"]
            self.tables_info[table_name] = {"columns": columns, "types": column_types}

    # ------------------------------------------------------------------
    # MySQL connection helper
    # ------------------------------------------------------------------

    def _get_mysql_connection(self):
        """Open and return a PyMySQL connection, or ``None`` on failure."""
        try:
            return pymysql.connect(
                host=self.mysql_config["host"],
                port=self.mysql_config["port"],
                user=self.mysql_config["user"],
                password=self.mysql_config["password"],
                database=self.mysql_config["database"],
                charset=self.mysql_config.get("charset", "utf8mb4"),
                cursorclass=pymysql.cursors.DictCursor,
            )
        except Exception as e:
            print(f"MySQL connection failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fill_template(self, template_input, debug: bool = False) -> str:
        """
        Fill all structured placeholders in *template_input* with real values.

        Accepts either a raw payload string or a full payload template dict.

        Fixed-type placeholders (``$int$``, ``$float$``, etc.) are replaced
        first; the remaining ``$table_N$`` / ``$column_tN_M$`` / ``$sample_tN_M$``
        placeholders are then filled using schema and sample data from MySQL.

        Args:
            template_input: A payload template dict or a plain payload string.
            debug:          Print verbose replacement trace when ``True``.

        Returns:
            The fully substituted SQL payload string.

        Raises:
            ValueError: If *template_input* is not a str or dict.
        """
        if isinstance(template_input, str):
            template = template_input
            expected_types: List[str] = []
            information_features = "specific database"
            if debug:
                print("Input type: string (no type constraints)")
        elif isinstance(template_input, dict):
            template = template_input.get("payload", "")
            # Copy the list to avoid modifying the original dict in-place:
            # .pop() calls on the original would shorten expected_types on
            # every reuse of the same template (a subtle data-corruption bug).
            expected_types = list(template_input.get("expected_types", []))
            information_features = template_input.get("information_features", "specific database")
            if debug:
                print(f"Input type: dict | expected_types: {expected_types} | info_features: {information_features}")
        else:
            raise ValueError("template_input must be a str or dict")

        # -------------------------------------------------------------------
        # Remove expected_types entries that correspond to fixed-type
        # placeholders (e.g. $int$ → "integer"), identified by position.
        # We must match by position — not by value — because $sysInfo$ and
        # $int$ may share the same type string ("integer"), and a value-based
        # filter would remove the wrong entry.
        # -------------------------------------------------------------------
        FIXED_PLACEHOLDER_TYPE_MAP = {
            "$int$": "integer",
            "$float$": "float",
            "$hex$": "hex",
            "$time$": "time",
            "$character$": "character",
            "$date$": "date",
        }
        FIXED_PLACEHOLDER_REPLACEMENTS = {
            "$int$": GetRandomAttribute.random_int_number,
            "$float$": GetRandomAttribute.random_float_number,
            "$hex$": GetRandomAttribute.random_hex_number,
            "$time$": GetRandomAttribute.random_time,
            "$character$": GetRandomAttribute.random_character,
            "$date$": GetRandomAttribute.random_date,
        }

        if expected_types:
            all_ph_matches = list(re.finditer(r"\$\w+\$", template))
            indices_to_remove = set()
            for m in all_ph_matches:
                ph = m.group(0)
                if ph in FIXED_PLACEHOLDER_TYPE_MAP:
                    ph_order = sum(1 for mm in all_ph_matches if mm.start() < m.start())
                    if ph_order < len(expected_types):
                        indices_to_remove.add(ph_order)
            for idx in sorted(indices_to_remove, reverse=True):
                expected_types.pop(idx)

        # Replace fixed-type placeholders
        for ph, replacer in FIXED_PLACEHOLDER_REPLACEMENTS.items():
            while ph in template:
                template = template.replace(ph, str(replacer()), 1)

        # Parse remaining structured placeholders
        placeholders = self._parse_marked_template(template)

        if debug:
            print(f"Placeholder count: {len(placeholders)}")
            for i, p in enumerate(placeholders):
                print(f"  {i}: {p['full_match']} (type={p['type']})")

        # Align expected_types with placeholder count
        if expected_types:
            if len(expected_types) != len(placeholders):
                print(
                    f"Warning: expected_types length ({len(expected_types)}) "
                    f"does not match placeholder count ({len(placeholders)})"
                )
                if len(expected_types) < len(placeholders):
                    expected_types.extend(["all"] * (len(placeholders) - len(expected_types)))
                else:
                    expected_types = expected_types[: len(placeholders)]
            for i, placeholder in enumerate(placeholders):
                placeholder["expected_type"] = expected_types[i]
                if debug:
                    print(f"  {placeholder['full_match']} → expected_type: {expected_types[i]}")
        else:
            for placeholder in placeholders:
                placeholder["expected_type"] = "all"
            if debug:
                print("No expected_types provided — all placeholders use 'all'")

        max_table_id = self._get_max_table_id(placeholders)
        table_assignments = self._assign_tables_with_types(max_table_id, placeholders, debug)

        replacement_values = []
        for placeholder in placeholders:
            value = self._get_marked_replacement(placeholder, table_assignments, information_features, debug)
            replacement_values.append(value)
            if debug:
                print(f"  {placeholder['full_match']} → {value}")

        # Replace from right-to-left to preserve character positions
        result = template
        for placeholder, value in reversed(list(zip(placeholders, replacement_values))):
            result = (
                result[: placeholder["start"]] + value + result[placeholder["end"] :]
            )

        return result

    # ------------------------------------------------------------------
    # Template parsing
    # ------------------------------------------------------------------

    def _parse_marked_template(self, template: str) -> List[Dict]:
        """
        Extract all structured placeholders from *template* in order.

        Supported formats:
        - ``$table_N$``
        - ``$column_tN_M$``
        - ``$sample_tN_M$``

        Unknown formats are included with ``type='unknown'``.
        """
        placeholders = []
        for match in re.finditer(r"\$(\w+)\$", template):
            full_match = match.group(0)
            content = match.group(1)
            placeholder = {
                "full_match": full_match,
                "start": match.start(),
                "end": match.end(),
            }
            if re.match(r"table_(\d+)", content):
                placeholder["type"] = "table"
                placeholder["table_id"] = re.match(r"table_(\d+)", content).group(1)
            elif re.match(r"column_t(\d+)_(\d+)", content):
                m = re.match(r"column_t(\d+)_(\d+)", content)
                placeholder["type"] = "column"
                placeholder["table_id"] = m.group(1)
                placeholder["column_id"] = m.group(2)
            elif re.match(r"sample_t(\d+)_(\d+)", content):
                m = re.match(r"sample_t(\d+)_(\d+)", content)
                placeholder["type"] = "sample"
                placeholder["table_id"] = m.group(1)
                placeholder["column_id"] = m.group(2)
            else:
                placeholder["type"] = "unknown"
                placeholder["content"] = content
            placeholders.append(placeholder)
        return placeholders

    def _get_max_table_id(self, placeholders: List[Dict]) -> int:
        """Return the highest numeric table ID referenced by *placeholders*."""
        return max(
            (int(p["table_id"]) for p in placeholders if "table_id" in p),
            default=0,
        )

    # ------------------------------------------------------------------
    # Table assignment
    # ------------------------------------------------------------------

    def _can_table_satisfy_constraints(
        self, table_name: str, type_constraints: Dict[str, str]
    ) -> bool:
        """
        Return ``True`` if *table_name* has at least one column that satisfies
        every constraint in *type_constraints*.
        """
        if not type_constraints:
            return True
        table_info = self.tables_info[table_name]
        for column_id, expected_type in type_constraints.items():
            if not self._filter_columns_by_type(
                table_info["columns"], table_info["types"], expected_type
            ):
                return False
        return True

    def _assign_tables_with_types(
        self, table_count: int, placeholders: List[Dict], debug: bool = False
    ) -> Dict[str, Dict]:
        """
        Assign an actual database table to each numeric table ID (1 … *table_count*).

        Attempts to find tables that satisfy the type constraints collected from
        the placeholder list; falls back to a random table if no compliant
        candidate is found within 50 attempts.
        """
        # Collect type constraints per table ID
        table_type_constraints: Dict[str, Dict[str, str]] = {}
        for ph in placeholders:
            if ph["type"] in ("column", "sample"):
                table_id = ph["table_id"]
                column_id = ph["column_id"]
                expected_type = ph.get("expected_type", "all")
                table_type_constraints.setdefault(table_id, {})
                existing = table_type_constraints[table_id].get(column_id)
                if existing is None:
                    table_type_constraints[table_id][column_id] = expected_type
                elif existing == "all":
                    table_type_constraints[table_id][column_id] = expected_type
                elif expected_type != "all" and expected_type != existing:
                    if debug:
                        print(
                            f"Warning: conflicting type constraints for column_id {column_id}: "
                            f"{existing} vs {expected_type} — keeping {existing}"
                        )

        if debug:
            print(f"Type constraints summary: {table_type_constraints}")

        assignments: Dict[str, Dict] = {}
        used_tables: set = set()

        for i in range(1, table_count + 1):
            table_id = str(i)
            type_constraints = table_type_constraints.get(table_id, {})
            selected_table = None

            for _ in range(50):
                candidate = random.choice(self.table_names)
                if len(self.table_names) >= table_count and candidate in used_tables:
                    continue
                if self._can_table_satisfy_constraints(candidate, type_constraints):
                    selected_table = candidate
                    used_tables.add(candidate)
                    break

            if selected_table is None:
                if debug:
                    print(f"Warning: no table satisfies constraints for table_id={table_id}; choosing randomly")
                selected_table = random.choice(self.table_names)

            table_info = self.tables_info[selected_table]
            all_columns = table_info["columns"]
            all_types = table_info["types"]

            if debug:
                print(f"Table {table_id} → {selected_table} | columns: {all_columns}")

            filtered_columns_by_id: Dict[str, List[str]] = {}
            for column_id, expected_type in type_constraints.items():
                filtered_columns_by_id[column_id] = self._filter_columns_by_type(
                    all_columns, all_types, expected_type
                )
                if debug:
                    print(
                        f"  column_id {column_id} (type={expected_type}): "
                        f"{filtered_columns_by_id[column_id]}"
                    )

            samples = self._get_table_samples(selected_table, all_columns)
            assignments[table_id] = {
                "table": selected_table,
                "columns": all_columns,
                "types": all_types,
                "samples": samples,
                "column_map": {},
                "type_constraints": type_constraints,
                "filtered_columns": filtered_columns_by_id,
            }

        return assignments

    # ------------------------------------------------------------------
    # Column filtering
    # ------------------------------------------------------------------

    def _filter_columns_by_type(
        self, columns: List[str], types: Dict[str, str], expected_type: str
    ) -> List[str]:
        """
        Return the subset of *columns* whose data type matches *expected_type*.

        Returns all columns unchanged when ``expected_type`` is ``"all"`` or
        ``"table"``.  Returns an empty list (not a fallback) when no match
        is found — the caller is responsible for fallback logic.
        """
        if expected_type in ("all", "table"):
            return columns

        allowed_db_types = self.TYPE_MAPPING.get(expected_type, [])
        if allowed_db_types is None:
            return columns

        filtered = []
        for col in columns:
            col_type = types.get(col, "").lower()
            if any(col_type == t or col_type.startswith(t) for t in allowed_db_types):
                filtered.append(col)
        return filtered

    # ------------------------------------------------------------------
    # Sample data retrieval
    # ------------------------------------------------------------------

    def _get_table_samples(self, table: str, columns: List[str]) -> Dict[str, str]:
        """
        Query MySQL for up to 100 rows from *table* and return one random
        non-NULL value per column.  Falls back to ``"NULL"`` when no data
        is available or the query fails.
        """
        connection = None
        try:
            connection = self._get_mysql_connection()
            if connection is None:
                return {col: "NULL" for col in columns}

            with connection.cursor() as cursor:
                quoted_columns = [f"`{col}`" for col in columns]
                sql = (
                    f"SELECT {', '.join(quoted_columns)} "
                    f"FROM {self.db_name}.`{table}` LIMIT 100"
                )
                cursor.execute(sql)
                rows = cursor.fetchall()

                if not rows:
                    return {col: "NULL" for col in columns}

                samples = {}
                for col in columns:
                    non_null_values = [
                        str(row[col])
                        for row in rows
                        if row.get(col) is not None and row.get(col) != ""
                    ]
                    samples[col] = random.choice(non_null_values) if non_null_values else "NULL"
                return samples

        except Exception as e:
            print(f"Warning: failed to read table {table} ({e})")
            return {col: "NULL" for col in columns}
        finally:
            if connection:
                connection.close()

    # ------------------------------------------------------------------
    # Replacement value generation
    # ------------------------------------------------------------------

    def _get_marked_replacement(
        self,
        placeholder: Dict,
        table_assignments: Dict,
        information_features: str,
        debug: bool = False,
    ) -> str:
        """
        Resolve a structured placeholder to its replacement string.

        Table names are returned with a ``db_name.`` prefix when
        ``information_features`` is not ``"specific database"``.
        """
        ptype = placeholder["type"]

        # $table_N$
        if ptype == "table":
            table_id = placeholder["table_id"]
            if table_id in table_assignments:
                table_name = table_assignments[table_id]["table"]
                if information_features == "specific database":
                    return table_name
                return f"{self.db_name}.{table_name}"
            return "unknown_table"

        # $column_tN_M$
        if ptype == "column":
            table_id = placeholder["table_id"]
            column_id = placeholder["column_id"]
            if table_id not in table_assignments:
                return "unknown_column"
            table_data = table_assignments[table_id]

            if column_id in table_data["column_map"]:
                column_name = table_data["column_map"][column_id]
            else:
                available = (
                    table_data["filtered_columns"].get(column_id)
                    or table_data["columns"]
                )
                if not available:
                    available = table_data["columns"]
                    if debug:
                        print(f"    Warning: filtered columns empty, using all columns")
                column_name = random.choice(available)
                table_data["column_map"][column_id] = column_name
                if debug:
                    print(
                        f"    Assigned column: {column_name} "
                        f"(type={table_data['types'].get(column_name)})"
                    )

            # Escape column names containing special characters
            if any(c in column_name for c in (" ", "-", "(")):
                return f"`{column_name}`"
            return column_name

        # $sample_tN_M$
        if ptype == "sample":
            table_id = placeholder["table_id"]
            column_id = placeholder["column_id"]
            if table_id not in table_assignments:
                return "NULL"
            table_data = table_assignments[table_id]

            if column_id not in table_data["column_map"]:
                available = (
                    table_data["filtered_columns"].get(column_id)
                    or table_data["columns"]
                )
                if not available:
                    available = table_data["columns"]
                column_name = random.choice(available)
                table_data["column_map"][column_id] = column_name
            else:
                column_name = table_data["column_map"][column_id]

            sample_value = table_data["samples"].get(column_name, "NULL")
            if sample_value == "NULL":
                return "NULL"
            return self._format_sample(sample_value, table_data["types"].get(column_name, "varchar"))

        # Unknown placeholder — return content verbatim
        return placeholder.get("content", "unknown")

    def _format_sample(self, sample: Any, data_type: str = "varchar") -> str:
        """
        Format a sample value for inclusion in a SQL string.

        Numeric types are returned unquoted; string and date types are
        single-quoted with internal single quotes escaped.
        """
        if sample is None or sample == "NULL":
            return "NULL"

        data_type = data_type.lower()

        numeric_types = [
            "int", "integer", "double", "float", "real", "numeric", "decimal",
            "bigint", "smallint", "tinyint",
        ]
        if data_type in numeric_types:
            return str(sample)

        if data_type in ("date", "datetime", "timestamp", "time"):
            return f"'{sample}'"

        if isinstance(sample, str):
            if sample.replace(".", "").replace("-", "").isdigit():
                if data_type in ("varchar", "char", "text", "nvarchar", "nchar",
                                 "clob", "blob", "string"):
                    return f"'{sample.replace(chr(39), chr(39)*2)}'"
                return sample
            return f"'{sample.replace(chr(39), chr(39)*2)}'"

        return str(sample)

    def test_connection(self) -> bool:
        """
        Test whether the MySQL connection can be established.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        connection = self._get_mysql_connection()
        if connection:
            connection.close()
            print(
                f"✓ MySQL connection successful: "
                f"{self.mysql_config['host']}:{self.mysql_config['port']}"
                f"/{self.mysql_config['database']}"
            )
            return True
        print("✗ MySQL connection failed")
        return False


# ---------------------------------------------------------------------------
# System-information template filler
# ---------------------------------------------------------------------------

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
                f"✓ MySQL connection successful: "
                f"{self.mysql_config['host']}:{self.mysql_config['port']}"
                f"/{self.mysql_config['database']}"
            )
            return True
        except Exception as e:
            print(f"✗ MySQL connection failed: {e}")
            return False


# ---------------------------------------------------------------------------
# Config loading helpers (module-level cache)
# ---------------------------------------------------------------------------

_MYSQL_CONFIG_CACHE: Optional[Dict[str, Any]] = None


def get_mysql_config(
    config_path=None, *, force_reload: bool = False
) -> Dict[str, Any]:
    """
    Load (and cache) the MySQL connection configuration from YAML.

    Args:
        config_path:  Path to ``database_connection.yaml``.  Defaults to
                      ``<project_root>/config/database_connection.yaml``.
        force_reload: Bypass the in-memory cache and reload from disk.

    Returns:
        MySQL configuration dict.
    """
    global _MYSQL_CONFIG_CACHE
    if _MYSQL_CONFIG_CACHE is not None and not force_reload:
        return _MYSQL_CONFIG_CACHE

    if config_path is None:
        project_root = Path(__file__).resolve().parents[2]
        config_path = project_root / "config" / "database_connection.yaml"
    else:
        config_path = Path(config_path)

    _MYSQL_CONFIG_CACHE = load_yaml_to_dict(str(config_path))
    return _MYSQL_CONFIG_CACHE


def get_gpt_config(config_path=None) -> Dict[str, Any]:
    """
    Load the GPT/LLM configuration from YAML.

    Args:
        config_path: Path to ``gpt_config.yaml``.  Defaults to
                     ``<project_root>/config/gpt_config.yaml``.

    Returns:
        LLM configuration dict.
    """
    if config_path is None:
        project_root = Path(__file__).resolve().parents[2]
        config_path = project_root / "config" / "gpt_config.yaml"
    else:
        config_path = Path(config_path)
    return load_yaml_to_dict(str(config_path))


# Module-level singletons — initialised once at import time
gpt_config = get_gpt_config()
gpt = LLM(api_key=gpt_config["api_key"], base_url=gpt_config.get("base_url"))
checker = SymbolChecker()


# ---------------------------------------------------------------------------
# Injection-SQL generation pipeline
# ---------------------------------------------------------------------------

def pipeline(
    sql_example: Dict[str, Any],
    payload_template: Dict[str, Any],
    db_schemas: List[Dict],
    sys_schemas: List[Dict],
    system_vars: List[Dict],
    comment_list: List[Dict],
    comment_flag: bool,
) -> Optional[Dict[str, Any]]:
    """
    Convert a raw SQL example + payload template into a labelled injection sample.

    Steps:
    1. Fill the payload template's placeholders (system info or DB-specific).
    2. Optionally append a deceptive natural-language comment.
    3. Insert the filled payload at the ``$$`` injection point in the SQL query.
    4. Validate bracket balance; fix with a closing ``)`` if needed.
    5. Return a structured dict with the injection SQL, metadata, and label.

    Args:
        sql_example:      A raw SQL query dict from ``sql_data_with_injection_point.json``.
        payload_template: A payload template dict from ``payloads.json`` (possibly mutated).
        db_schemas:       List of all database schemas.
        sys_schemas:      List of MySQL system-table schemas.
        system_vars:      List of MySQL system variable definitions.
        comment_list:     Repository of pre-written deceptive comments.
        comment_flag:     Whether to append a deceptive comment to the payload.

    Returns:
        An injection sample dict, or ``None`` if generation failed.
    """

    # ------------------------------------------------------------------
    # Nested helpers
    # ------------------------------------------------------------------

    def identify_difficulty(annotator: bool, comment: bool, information_features: str) -> str:
        """Assign a difficulty label based on query and payload metadata."""
        if information_features == "constant":
            return "simple"
        if information_features == "system information":
            return "medium"
        if information_features == "specific database":
            if annotator and comment:
                return "hard"
            if annotator and not comment:
                return "medium"
            return "hard"
        return "medium"

    def generate_comment(
        payload_type: str,
        payload_template_str: str,
        payload: str,
        comment_list: List[Dict],
    ) -> str:
        """
        Generate a deceptive natural-language comment to append to the payload.

        Randomly selects one of three strategies:
        - **Irrelevant text dilution**: random benign-looking text
        - **Authoritative statement**: authority-sounding assertion
        - **Rational explanation**: LLM-generated contextual explanation
        """
        comment_type = random.choice(
            ["Rational explanation", "Irrelevant text dilution", "Authoritative statement"]
        )
        if comment_type == "Irrelevant text dilution":
            candidates = [c for c in comment_list if c["type"] == "Irrelevant text dilution"]
            return random.choice(candidates)["comment"]
        if comment_type == "Authoritative statement":
            candidates = [c for c in comment_list if c["type"] == "Authoritative statement"]
            return random.choice(candidates)["comment"]
        # Rational explanation — use LLM
        project_root = Path(__file__).resolve().parents[2]
        templates_dir = project_root / "prompt_templates"
        prompt = load_prompt_template(templates_dir, "generate_comment.j2").render(
            payload_type=payload_type,
            payload_template=payload_template_str,
            payload=payload,
        )
        return gpt.generate(
            prompt=prompt,
            model=gpt_config.get("model", "gpt-3.5-turbo"),
            temperature=gpt_config.get("temperature", 0.5),
            max_tokens=gpt_config.get("max_tokens", 1024),
        )

    def insert_payload(sql: str, payload: str) -> Optional[str]:
        """
        Insert *payload* into *sql* at the ``$$`` injection point.

        Handles two contexts:
        - **String context** (``$$`` is followed by ``'``): keep the leading
          quote of the payload.
        - **Non-string context**: strip the leading quote from the payload.

        Also removes trailing ``--`` comment terminators that would be
        redundant (i.e., followed only by whitespace or nothing), and attempts
        to fix bracket imbalances by inserting a closing ``)`` before ``--``.
        """

        def remove_first_char(text: str) -> str:
            return text[1:] if text else text

        def insert_char_at_position(text: str, position: int, char: str) -> str:
            return text[:position] + char + text[position:]

        def remove_unnecessary_comments(sql_text: str) -> str:
            """
            Remove ``--`` terminators that appear at the very end of the string
            or are followed only by whitespace — they are structurally redundant.
            """
            for match in reversed(list(re.finditer(r"--", sql_text))):
                comment_pos = match.start()
                comment_end = match.end()
                if comment_end >= len(sql_text):
                    sql_text = sql_text[:comment_pos]
                elif sql_text[comment_end:].strip() == "":
                    sql_text = sql_text[:comment_pos]
            return sql_text

        if not isinstance(sql, str) or not isinstance(payload, str):
            return None

        try:
            matches = list(re.finditer(r"\$\$", sql))
            if not matches:
                return None
            positions = [m.start() for m in matches]

            try:
                is_string_context = sql[positions[0] + 2] == "'"
            except IndexError:
                is_string_context = False

            if is_string_context:
                injection_sql = sql.replace("$$", payload)
            else:
                injection_sql = sql.replace("$$", remove_first_char(payload))

            injection_sql = remove_unnecessary_comments(injection_sql)

            # Check bracket balance in the fragment before any comment terminator
            _checker = SymbolChecker()
            effective_sql = injection_sql.split("--")[0] if "--" in injection_sql else injection_sql
            balanced, _ = _checker.check_balanced(effective_sql)

            if not balanced:
                comment_matches = list(re.finditer(r"--", injection_sql))
                bracket_pos = comment_matches[0].start() if comment_matches else len(injection_sql)
                injection_sql = insert_char_at_position(injection_sql, bracket_pos, ")")
                injection_sql = remove_unnecessary_comments(injection_sql)

            return injection_sql

        except Exception as e:
            print(f"Error inserting payload: {e}")
            return None

    # ------------------------------------------------------------------
    # Main pipeline logic
    # ------------------------------------------------------------------

    mysql_config = get_mysql_config().copy()
    mysql_config["database"] = sql_example["db"]

    injection_sql_example = None

    # Fill payload placeholders
    if payload_template["expected_types"] is None:
        raw_payload = payload_template["payload"]
    else:
        info_features = payload_template["information_features"]
        if info_features == "system information":
            if "table" in payload_template["expected_types"]:
                sys_schema = random.choice(sys_schemas)
                filler = SpecificDatabaseTemplateFiller(sys_schema, mysql_config)
                raw_payload = filler.fill_template(payload_template)
            else:
                filler = SystemInformationTemplateFiller(system_vars, mysql_config)
                raw_payload = filler.fill_template(payload_template)
        elif info_features == "specific database":
            schema = next(
                (s for s in db_schemas if s["database_name"] == sql_example["db"]), {}
            )
            filler = SpecificDatabaseTemplateFiller(schema, mysql_config)
            raw_payload = filler.fill_template(payload_template)
        else:
            # constant — expected_types is non-None but there are no placeholders
            raw_payload = payload_template["payload"]

    # Non-annotator queries never have deceptive comments
    if not sql_example["annotator"]:
        comment_flag = False

    # Optionally append a deceptive comment
    if comment_flag:
        payload = str(raw_payload) + str(
            generate_comment(
                payload_template["type"],
                payload_template["payload"],
                raw_payload,
                comment_list,
            )
        )
    else:
        payload = str(raw_payload)

    if sql_example["sql"] is None or payload is None:
        return injection_sql_example

    injection_sql = insert_payload(sql_example["sql"], payload)
    effective_sql = injection_sql.split("--")[0]
    balanced, message = checker.check_balanced(effective_sql)

    if not balanced:
        print(f"'{effective_sql}'\n  -> {balanced}: {message}\n")
    else:
        injection_sql_example = {
            "sql": injection_sql,
            "original_sql": sql_example,
            "payload_template": payload_template,
            "payload": payload,
            "label": False,
            "comment": comment_flag,
            "difficulty": identify_difficulty(
                sql_example["annotator"],
                comment_flag,
                payload_template["information_features"],
            ),
        }

    return injection_sql_example


def batch_generate_injection_sqls(
    expected_example_num: int,
    raw_sqls: List[Dict],
    payloads: List[Dict],
    db_schemas: List[Dict],
    sys_schemas: List[Dict],
    system_vars: List[Dict],
    comment_list: List[Dict],
    comment_rate: float,
) -> List[Dict]:
    """
    Generate *expected_example_num* injection SQL samples by randomly sampling
    from *raw_sqls* and *payloads*.

    Args:
        expected_example_num: Target number of generated samples.
        raw_sqls:             List of raw SQL example dicts.
        payloads:             List of payload template dicts.
        db_schemas:           Database schemas list.
        sys_schemas:          System-table schemas list.
        system_vars:          System variable definitions.
        comment_list:         Deceptive comment repository.
        comment_rate:         Probability (0–1) of appending a comment per sample.

    Returns:
        List of successfully generated injection SQL sample dicts.
    """
    count = 0
    injection_sql_examples = []
    while count < expected_example_num:
        comment_flag = random.random() < comment_rate
        sample = pipeline(
            random.choice(raw_sqls),
            random.choice(payloads),
            db_schemas,
            sys_schemas,
            system_vars,
            comment_list,
            comment_flag,
        )
        if sample is not None:
            injection_sql_examples.append(sample)
        count += 1
    return injection_sql_examples
