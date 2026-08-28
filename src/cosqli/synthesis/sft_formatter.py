"""
Schema pre-processing and SFT data formatting.

Provides utilities to:
- Convert a schema dict into a sequence of ``CREATE TABLE`` DDL statements.
- Format SQL examples into SFT training records (OpenAI messages format).
"""

from typing import Any, Dict, List, Mapping, Sequence

from cosqli.prompting import PromptMode, parse_prompt_mode

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

def _database_name(sql_entry: Mapping[str, Any]) -> str | None:
    """Extract the database name from a raw or synthesized SQL record."""
    db_name = sql_entry.get("db")
    if db_name is None and isinstance(sql_entry.get("original_sql"), Mapping):
        db_name = sql_entry["original_sql"].get("db")
    return str(db_name) if db_name is not None else None


def _schema_by_database(
    schemas: Mapping[str, Dict[str, Any]] | Sequence[Dict[str, Any]] | None,
) -> Dict[str, Dict[str, Any]]:
    """Return a database-indexed view of supported schema input forms."""
    if schemas is None:
        return {}
    if isinstance(schemas, Mapping):
        return dict(schemas)
    return {
        str(schema["database_name"]): schema
        for schema in schemas
        if schema.get("database_name")
    }


def _schema_text_for_entry(
    sql_entry: Mapping[str, Any],
    schemas: Mapping[str, Dict[str, Any]] | Sequence[Dict[str, Any]] | None,
) -> str:
    """Resolve schema DDL, rejecting incomplete schema-aware examples."""
    db_name = _database_name(sql_entry)
    if not db_name:
        raise ValueError("schema_aware prompt requires a database name")
    schema = _schema_by_database(schemas).get(db_name)
    if schema is None:
        raise ValueError(f"schema_aware prompt has no schema for database: {db_name}")
    return schema_to_create_statements(schema)


def render_user_prompt(
    sql_entry: Mapping[str, Any],
    schemas: Mapping[str, Dict[str, Any]] | Sequence[Dict[str, Any]] | None,
    prompt_mode: PromptMode | str,
) -> str:
    """Render the only model-visible SQL context for one SFT record."""
    mode = parse_prompt_mode(prompt_mode)
    sql = str(sql_entry.get("sql", ""))
    if mode is PromptMode.QUERY_ONLY:
        return f"SQL Query:\n{sql}"
    schema_text = _schema_text_for_entry(sql_entry, schemas)
    return f"SQL Query:\n{sql}\n\nDatabase Schema:\n{schema_text}"


def create_sft_format(
    sql_entry: Dict[str, Any],
    schemas: Mapping[str, Dict[str, Any]] | Sequence[Dict[str, Any]] | None,
    format_type: str = "openai",
    prompt_mode: PromptMode | str = PromptMode.QUERY_ONLY,
) -> Dict[str, Any]:
    """Convert one SQL example into an SFT record for the selected prompt mode."""
    mode = parse_prompt_mode(prompt_mode)

    label = sql_entry.get("label", True)

    metadata: Dict[str, Any] = {}
    if not label:
        metadata = {
            "technique": sql_entry["technique"],
            "reference_scope": sql_entry["reference_scope"],
            "comment_state": sql_entry["comment_state"],
            "difficulty": sql_entry.get("difficulty", "medium"),
        }

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
                    "content": render_user_prompt(sql_entry, schemas, mode),
                },
                {
                    "role": "assistant",
                    "content": "malicious" if not label else "benign",
                },
            ],
            "sql": sql_entry.get("sql", ""),
            "label": label,
            "prompt_mode": mode.value,
            **metadata,
        }
    else:
        raise ValueError(f"SFTFormatter currently only supports format_type='openai'")

def batch_process_to_sft(
    sql_data: Sequence[Dict[str, Any]],
    schemas: Mapping[str, Dict[str, Any]] | Sequence[Dict[str, Any]] | None,
    format_type: str = "openai",
    prompt_mode: PromptMode | str = PromptMode.QUERY_ONLY,
) -> List[Dict[str, Any]]:
    """Batch convert every SQL example to SFT format without silent drops."""
    mode = parse_prompt_mode(prompt_mode)
    schema_index = _schema_by_database(schemas) if mode is PromptMode.SCHEMA_AWARE else None
    return [
        create_sft_format(entry, schema_index, format_type, mode)
        for entry in sql_data
    ]
