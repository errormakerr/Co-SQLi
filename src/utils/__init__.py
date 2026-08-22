"""
SQLI Utilities Package

Common helpers for file I/O, LLM interaction,
template loading, and payload clustering.
"""

from .json_operation import read_json_file, write_json_file, read_jsonl_file, write_jsonl_file
from .yaml_operation import load_yaml_to_dict
from .j2_operation import load_prompt_template
from .cluster import (
    COMMENT_STATES,
    NORMAL_CLUSTER_KEY,
    REFERENCE_SCOPES,
    TAXONOMY_VERSION,
    TECHNIQUES,
    ClusterKey,
    PayloadCategoryKey,
    VALID_PAYLOAD_CATEGORIES,
    all_attack_cluster_keys,
    cluster_injection_sqls,
    cluster_payload_templates,
    get_injection_cluster_keys,
    get_single_key_of_injection_sql,
    get_single_key_of_payload_template,
)

__all__ = [
    # File I/O
    "read_json_file",
    "write_json_file",
    "read_jsonl_file",
    "write_jsonl_file",
    # Config
    "load_yaml_to_dict",
    # Templates
    "load_prompt_template",
    # Clustering
    "TAXONOMY_VERSION",
    "NORMAL_CLUSTER_KEY",
    "TECHNIQUES",
    "REFERENCE_SCOPES",
    "COMMENT_STATES",
    "VALID_PAYLOAD_CATEGORIES",
    "ClusterKey",
    "PayloadCategoryKey",
    "all_attack_cluster_keys",
    "cluster_injection_sqls",
    "cluster_payload_templates",
    "get_injection_cluster_keys",
    "get_single_key_of_injection_sql",
    "get_single_key_of_payload_template",
]
