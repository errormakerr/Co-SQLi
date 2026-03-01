# convert_to_sft_format.py
# 用途: 将 SQL 数据和 Schema 数据合并生成 SFT 训练数据
# 用法:
#   python schema_reprecess.py --sql_file train_sqls.json --schema_file mysql_schema.json --output output.jsonl

import json
import argparse
from typing import Dict, List, Any

# 类型映射
TYPE_MAP = {
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
    "timestamp": "TIMESTAMP"
}

def map_type(t: str) -> str:
    """映射数据类型到标准SQL类型"""
    if not t:
        return "VARCHAR"
    tt = str(t).lower()
    for k, v in TYPE_MAP.items():
        if k in tt:
            return v
    return tt.upper()  # 保持原类型大写

def load_schemas(schema_file: str) -> Dict[str, Dict]:
    """
    从 mysql_schema.json 加载所有数据库的 schema
    返回: {database_name: schema_dict, ...}
    """
    with open(schema_file, 'r', encoding='utf-8') as f:
        schemas = json.load(f)
    
    schema_dict = {}
    for db_schema in schemas:
        db_name = db_schema.get("database_name")
        if db_name:
            schema_dict[db_name] = db_schema
    
    return schema_dict

def schema_to_create_statements(schema: Dict) -> str:
    """
    将 schema 字典转换为 CREATE TABLE 语句
    """
    db_name = schema.get("database_name", "unknown_db")
    tables = schema.get("tables", [])
    
    lines = []
    lines.append(f"-- Database: {db_name}\n")
    
    for table in tables:
        table_name = table.get("table_name", "unknown_table")
        columns = table.get("columns", [])
        
        lines.append(f"CREATE TABLE `{table_name}` (")
        
        col_definitions = []
        for col in columns:
            col_name = col.get("column_name", "unknown_col")
            col_type = map_type(col.get("data_type", "VARCHAR"))
            
            # 处理包含特殊字符的列名（用反引号包裹）
            if ' ' in col_name or '/' in col_name or '(' in col_name or ')' in col_name:
                col_definitions.append(f"    `{col_name}` {col_type}")
            else:
                col_definitions.append(f"    {col_name} {col_type}")
        
        if col_definitions:
            lines.append(",\n".join(col_definitions))
        else:
            lines.append("    -- No columns defined")
        
        lines.append(");\n")
    
    return "\n".join(lines)

def load_sql_data(sql_file: str) -> List[Dict]:
    """
    加载 train_sqls.json 中的 SQL 数据
    """
    with open(sql_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data

def create_sft_format(sql_entry: Dict, schema_text: str, format_type: str = "instruction") -> Dict:
    """
    创建 SFT 训练数据格式
    
    format_type 可选:
    - "instruction": 指令格式 (input + output)
    - "conversation": 对话格式 (messages)
    - "alpaca": Alpaca 格式 (instruction + input + output)
    """
    # 尝试从多个位置获取数据库名
    db_name = sql_entry.get("db")
    if db_name is None and "original_sql" in sql_entry:
        db_name = sql_entry["original_sql"].get("db", "unknown")
    elif db_name is None:
        db_name = "unknown"
    
    sql = sql_entry.get("sql", "")
    label = sql_entry.get("label", True)
    information_features = 'normal'
    type = 'normal'
    difficulty = 'normal'
    annotator = 'normal'
    comment = 'normal'
    
    if not sql_entry['label']:
        information_features = sql_entry['payload_template']['information_features']
        type = sql_entry['payload_template']['type']
        difficulty = sql_entry['difficulty']
        annotator = sql_entry['original_sql']['annotator']
        comment = sql_entry['comment']
    
    if format_type == "instruction":
        # instruction + input (sql + schema) + output (label) 格式
        return {
            "instruction": "You are a SQL security expert. Given a SQL query and its corresponding database schema, determine whether the SQL query is malicious (contains SQL injection attacks) or benign. Answer with 'malicious' if the query contains attack patterns, or 'benign' if it's a normal query.",
            "input": f"SQL Query:\n{sql}\n\nDatabase Schema:\n{schema_text}",
            "output": "malicious" if not label else "benign"
        }
    
    elif format_type == "openai":
        # OpenAI 对话格式
        return {
            "messages": [
                {
                    "role": "system",
                    "content": "You are a SQL security expert. Your task is to analyze SQL queries and determine whether they are malicious (contain SQL injection attacks) or benign (normal queries). You only need to output the label (malicious or benign), no other extra text output is required."
                },
                {
                    "role": "user",
                    "content": f"SQL Query:\n{sql}\n\nDatabase Schema:\n{schema_text}\n\nIs this SQL query malicious or benign?"
                },
                {
                    "role": "assistant",
                    "content": "malicious" if not label else "benign"
                }
            ],
            "sql": sql,
            "label": label,
            "information_features": information_features,
            "type": type,
            "difficulty": difficulty,
            "annotator": str(annotator), 
            "comment": str(comment)
        }
    
    elif format_type == "conversation":
        # 对话格式（适合 ChatML 等）
        return {
            "messages": [
                {
                    "role": "system",
                    "content": "You are a SQL expert. Generate SQL queries based on the given database schema."
                },
                {
                    "role": "user",
                    "content": f"Here is the database schema:\n\n{schema_text}\n\nPlease provide a SQL query for this database."
                },
                {
                    "role": "assistant",
                    "content": sql
                }
            ],
            "label": label,
            "database": db_name
        }
    
    elif format_type == "alpaca":
        # Alpaca 格式
        return {
            "instruction": "Generate a SQL query based on the provided database schema.",
            "input": schema_text,
            "output": sql,
            "label": label,
            "database": db_name
        }
    
    else:
        raise ValueError(f"Unknown format_type: {format_type}")

def process_data_original(sql_file: str, schema_file: str, output_file: str, format_type: str = "instruction"):
    """
    主处理函数：合并 SQL 数据和 Schema，生成 SFT 格式数据
    """
    print(f"Loading schemas from {schema_file}...")
    schemas = load_schemas(schema_file)
    print(f"Loaded {len(schemas)} database schemas")
    
    print(f"Loading SQL data from {sql_file}...")
    sql_data = load_sql_data(sql_file)
    print(f"Loaded {len(sql_data)} SQL entries")
    
    print(f"Generating SFT format data...")
    output_data = []
    missing_schemas = set()
    
    for idx, sql_entry in enumerate(sql_data):
        # 尝试从多个位置获取数据库名
        db_name = sql_entry.get("db")
        if db_name is None and "original_sql" in sql_entry:
            db_name = sql_entry["original_sql"].get("db")
        
        if db_name is None or db_name not in schemas:
            missing_schemas.add(str(db_name))
            continue
        
        # 获取对应的 schema 并转换为 CREATE TABLE 语句
        schema_text = schema_to_create_statements(schemas[db_name])
        
        # 生成 SFT 格式
        sft_entry = create_sft_format(sql_entry, schema_text, format_type)
        output_data.append(sft_entry)
        
        if (idx + 1) % 1000 == 0:
            print(f"Processed {idx + 1}/{len(sql_data)} entries...")
    
    if missing_schemas:
        print(f"\nWarning: {len(missing_schemas)} database(s) not found in schema file:")
        for db in sorted(missing_schemas):
            print(f"  - {db}")
    
    print(f"\nWriting {len(output_data)} entries to {output_file}...")
    with open(output_file, 'w', encoding='utf-8') as f:
        for entry in output_data:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    
    print(f"Done! Output saved to {output_file}")
    print(f"Successfully processed: {len(output_data)}/{len(sql_data)} entries")

def process_data(sql_data: List, schemas: Dict, format_type: str = "openai"):
    """
    主处理函数：合并 SQL 数据和 Schema，生成 SFT 格式数据
    """
    print(f"Generating SFT format data...")
    output_data = []
    missing_schemas = set()
    
    for idx, sql_entry in enumerate(sql_data):
        # 尝试从多个位置获取数据库名
        db_name = sql_entry.get("db")
        if db_name is None and "original_sql" in sql_entry:
            db_name = sql_entry["original_sql"].get("db")
        
        if db_name is None or db_name not in schemas:
            missing_schemas.add(str(db_name))
            continue
        
        # 获取对应的 schema 并转换为 CREATE TABLE 语句
        schema_text = schema_to_create_statements(schemas[db_name])
        
        # 生成 SFT 格式
        sft_entry = create_sft_format(sql_entry, schema_text, format_type)
        output_data.append(sft_entry)
        
        if (idx + 1) % 1000 == 0:
            print(f"Processed {idx + 1}/{len(sql_data)} entries...")
    
    if missing_schemas:
        print(f"\nWarning: {len(missing_schemas)} database(s) not found in schema file:")
        for db in sorted(missing_schemas):
            print(f"  - {db}")
    return output_data
    


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert SQL data and schema to SFT training format"
    )
    parser.add_argument(
        "--sql_file",
        default=r"/home/panhao/project/SQLI/data/benchmark/test_sqls.json",
        help="Path to SQL data file (train_sqls.json)"
    )
    parser.add_argument(
        "--schema_file",
        default=r"/home/panhao/project/SQLI/data/raw_datas_for_generation/schema.json",
        help="Path to schema file (mysql_schema.json)"
    )
    parser.add_argument(
        "--output",
        default=r"/home/panhao/project/SQLI/data/benchmark/test_datas_openai_format.jsonl",
        help="Output file path (JSONL format)"
    )
    parser.add_argument(
        "--format",
        choices=["instruction", "openai", "conversation", "alpaca"],
        default="openai",
        help="Output format type: instruction, openai, conversation, or alpaca"
    )
    
    args = parser.parse_args()
    
    process_data_original(
        sql_file=args.sql_file,
        schema_file=args.schema_file,
        output_file=args.output,
        format_type=args.format
    )
