"""
Schema pre-processing and SFT data formatting.

Provides utilities to:
- Convert a schema dict into a sequence of ``CREATE TABLE`` DDL statements.
- Format SQL examples into SFT training records (OpenAI messages format).
"""

from typing import Any, Dict, List, Union

# ---------------------------------------------------------------------------
# Type normalisation
# ---------------------------------------------------------------------------

TYPE_MAP: Dict[str, str] = {
    "text": "VARCHAR",
    "varchar": "VARCHAR",
    "char": "VARCHAR",
    "string": "VARCHAR",
    "int": "INTEGER",
    "integer": "INTEGER",
    "real": "REAL",
    "float": "REAL",
    "double": "DOUBLE",
    "number": "DECIMAL",
    "decimal": "DECIMAL",
    "bool": "BOOLEAN",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "datetime": "DATETIME",
    "timestamp": "TIMESTAMP",
}

def map_type(t: str) -> str:
    """
    Normalise *t* to a standard SQL data-type string.
    """
    if not t:
        return "VARCHAR"
    t_lower = str(t).lower()
    for key, value in TYPE_MAP.items():
        if key in t_lower:
            return value
    return t_lower.upper()

# ---------------------------------------------------------------------------
# Schema → DDL conversion
# ---------------------------------------------------------------------------

def schema_to_create_statements(schema: Dict) -> str:
    """
    Render a schema dict as a series of ``CREATE TABLE`` DDL statements.
    """
    db_name = schema.get("database_name", "unknown_db")
    tables = schema.get("tables", [])

    lines: List[str] = [f"-- Database: {db_name}\n"]

    for table in tables:
        table_name = table.get("table_name", "unknown_table")
        columns = table.get("columns", [])

        lines.append(f"CREATE TABLE `{table_name}` (")

        col_defs: List[str] = []
        for col in columns:
            col_name = col.get("column_name", "unknown_col")
            col_type = map_type(col.get("data_type", "VARCHAR"))
            if any(c in col_name for c in (" ", "/", "(", ")")):
                col_defs.append(f"    `{col_name}` {col_type}")
            else:
                col_defs.append(f"    {col_name} {col_type}")

        if col_defs:
            lines.append(",\n".join(col_defs))
        else:
            lines.append("    -- No columns defined")

        lines.append(");\n")

    return "\n".join(lines)

# ---------------------------------------------------------------------------
# SFT record formatting
# ---------------------------------------------------------------------------

def create_sft_format(
    sql_entry: Dict[str, Any],
    schemas: Union[Dict[str, Dict], List[Dict]],
    format_type: str = "openai",
    schema_mode: str = "aware",
) -> Dict[str, Any]:
    """
    Convert a single SQL example into an SFT training record using schema dicts directly.

    Args:
        sql_entry:   The SQL example record.
        schemas:     Schema dict (db_name -> schema) or a list of schemas.
        format_type: Output format, currently only ``"openai"`` is supported.
        schema_mode: ``"aware"`` (default) — include real DDL when resolvable,
                     falling back to ``"N/A"`` when the schema is missing or the
                     entry has no ``db``.  ``"free"`` — use the literal string
                     ``"N/A"`` for every record regardless of the schema map.
    """
    if schema_mode == "free":
        schema_text = "N/A"
    else:
        db_name = sql_entry.get("db")
        if db_name is None and "original_sql" in sql_entry:
            db_name = sql_entry["original_sql"].get("db")

        # If the schema cannot be found, fallback to "N/A" (same literal as
        # the context-free branch and the evaluation test files).
        schema_text = ""
        if db_name:
            if isinstance(schemas, dict) and db_name in schemas:
                schema_text = schema_to_create_statements(schemas[db_name])
            elif isinstance(schemas, list):
                for schema_dict in schemas:
                    if schema_dict.get("database_name") == db_name:
                        schema_text = schema_to_create_statements(schema_dict)
                        break

        if not schema_text:
            schema_text = "N/A"

    sql = sql_entry.get("sql", "")
    label = sql_entry.get("label", True)

    information_features = "normal"
    attack_type = "normal"
    difficulty = "normal"
    annotator = "normal"
    comment = "normal"

    if not sql_entry["label"]:
        if "payload_template" in sql_entry:
            information_features = sql_entry["payload_template"].get("information_features", "normal")
            attack_type = sql_entry["payload_template"].get("type", "normal")
        difficulty = sql_entry.get("difficulty", "normal")
        if "original_sql" in sql_entry:
            annotator = sql_entry["original_sql"].get("annotator", "normal")
        comment = sql_entry.get("comment", "normal")

    if format_type == "openai":
        return {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a SQL security expert. Your task is to analyze SQL queries "
                        "and determine whether they are malicious (contain SQL injection "
                        "attacks) or benign (normal queries). You only need to output the "
                        "label (malicious or benign), no other extra text output is required."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"SQL Query:\n{sql}\n\nDatabase Schema:\n{schema_text}\n\n"
                        "Is this SQL query malicious or benign?"
                    ),
                },
                {
                    "role": "assistant",
                    "content": "malicious" if not label else "benign",
                },
            ],
            "sql": sql,
            "label": label,
            "information_features": information_features,
            "type": attack_type,
            "difficulty": difficulty,
            "annotator": str(annotator),
            "comment": str(comment),
        }
    else:
        raise ValueError(f"SFTFormatter currently only supports format_type='openai'")

def batch_process_to_sft(
    sql_data: List[Dict],
    schemas: Dict[str, Dict],
    format_type: str = "openai",
    schema_mode: str = "aware",
) -> List[Dict]:
    """Batch convert SQL examples to SFT format.

    In ``"aware"`` mode (default) entries whose ``db`` resolves to a known
    schema render with the real DDL; entries whose ``db`` is ``None`` (e.g. the
    public-dataset benigns merged into ``normal_sqls.json``) fall through with
    ``schema_text = "N/A"`` rather than being silently dropped; entries whose
    ``db`` is set but unknown are skipped (preserving the prior behaviour for
    accidentally malformed records).

    In ``"free"`` mode every entry is emitted and the schema text is
    unconditionally ``"N/A"``.
    """
    output_data = []

    # Check if schemas is a list and convert to DB indexed dict
    schema_dict = {}
    if isinstance(schemas, list):
        for s in schemas:
            if s.get("database_name"):
                schema_dict[s["database_name"]] = s
    else:
        schema_dict = schemas

    for entry in sql_data:
        if schema_mode == "free":
            sft_entry = create_sft_format(
                entry, schema_dict, format_type, schema_mode="free"
            )
            output_data.append(sft_entry)
            continue

        db_name = entry.get("db")
        if db_name is None and "original_sql" in entry:
            db_name = entry["original_sql"].get("db")

        if db_name is None:
            # No schema (e.g. public-dataset benign): emit with N/A.
            sft_entry = create_sft_format(
                entry, schema_dict, format_type, schema_mode="aware"
            )
            output_data.append(sft_entry)
        elif db_name in schema_dict:
            sft_entry = create_sft_format(
                entry, schema_dict, format_type, schema_mode="aware"
            )
            output_data.append(sft_entry)
        # else: db set but unknown -> skip (preserve original behaviour)

    return output_data
