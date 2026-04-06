"""
Fill ``$table_N$``, ``$column_tN_M$``, and ``$sample_tN_M$`` placeholders
by querying a real MySQL schema and sampling actual table/column/value data.
"""

from __future__ import annotations

import re
import random
from typing import Any, Dict, List, Optional

import pymysql

from Attacker.random_attributes import GetRandomAttribute


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
        # placeholders (e.g. $int$ -> "integer"), identified by position.
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
                    print(f"  {placeholder['full_match']} -> expected_type: {expected_types[i]}")
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
                print(f"  {placeholder['full_match']} -> {value}")

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

    MAX_TABLE_ASSIGNMENT_ATTEMPTS = 50

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
        Assign an actual database table to each numeric table ID (1 ... *table_count*).

        Attempts to find tables that satisfy the type constraints collected from
        the placeholder list; falls back to a random table if no compliant
        candidate is found within ``MAX_TABLE_ASSIGNMENT_ATTEMPTS`` attempts.
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

            for _ in range(self.MAX_TABLE_ASSIGNMENT_ATTEMPTS):
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
                print(f"Table {table_id} -> {selected_table} | columns: {all_columns}")

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
                f"MySQL connection successful: "
                f"{self.mysql_config['host']}:{self.mysql_config['port']}"
                f"/{self.mysql_config['database']}"
            )
            return True
        print("MySQL connection failed")
        return False
