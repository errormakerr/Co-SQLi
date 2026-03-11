"""
载荷类型识别器

识别 SQL 注入载荷的攻击类型和信息特征。
"""

import re
from enum import Enum
from typing import Dict, Tuple


class AttackType(Enum):
    """攻击类型枚举"""
    ERROR_BASE = "Error base attack"
    UNION_QUERY = "Union-query attack"
    TAUTOLOGIES = "Tautologies attack"
    PIGGY_BACKED = "Piggy-backed queries attacks"
    BOOLEAN_INFERENCE = "Boolean base inference attack"
    TIME_INFERENCE = "Time base inference attack"
    UNKNOWN = "Unknown"


class InfoFeature(Enum):
    """信息特征枚举"""
    CONSTANT = "constant"
    SYSTEM_INFO = "system information"
    SPECIFIC_DB = "specific database"
    UNKNOWN = "unknown"


# ============================================================
# 攻击类型识别模式
# ============================================================

TYPE_PATTERNS = {
    AttackType.ERROR_BASE: [
        r"CAST\s*\(",
        r"CONVERT\s*\(",
        r"SQRT\s*\(",
        r"LOG\d*\s*\(",
        r"LN\s*\(",
        r"MOD\s*\(",
        r"extractvalue\s*\(",
        r"updatexml\s*\(",
        r"GTID_SUBSET\s*\(",
        r"GTID_SUBTRACT\s*\(",
        r"TIME\s*\(['\"]",
        r"DATE\s*\(['\"]",
        r"TO_DAYS\s*\(",
        r"SUBSTR\s*\([^,]+,\s*['\"]",  # SUBSTR with invalid params
        r"\/\s*\(SELECT\s+0\)",
        r"9223372036854775807",  # 溢出值
        r"-9223372036854775808",
        r"1\.7976931348623157e\+308",
    ],
    AttackType.UNION_QUERY: [
        r"\bUNION\b",
        r"\bORDER\s+BY\s+\d",
        r"\bGROUP\s+BY\s+\d",
    ],
    AttackType.TAUTOLOGIES: [
        r"'\s+OR\s+",
        r"'\s+AND\s+\d\s*=\s*\d",
        r"'\s+AND\s+'[^']+'\s*=\s*'[^']+'",
    ],
    AttackType.PIGGY_BACKED: [
        r";\s*SELECT\b",
        r";\s*DELETE\b",
        r";\s*INSERT\b",
        r";\s*UPDATE\b",
        r";\s*DROP\b",
        r";\s*TRUNCATE\b",
        r";\s*CREATE\b",
    ],
    AttackType.TIME_INFERENCE: [
        r"SLEEP\s*\(",
        r"BENCHMARK\s*\(",
        r"SELECT\s+COUNT\s*\(\*\)\s+FROM\s+\w+\s*,\s*\w+",
    ],
    AttackType.BOOLEAN_INFERENCE: [
        r"'\s+AND\s+.*(?:SUBSTR|SUBSTRING|LEFT|RIGHT|ASCII|ORD)",
        r"'\s+AND\s+.*(?:LENGTH|COUNT)",
        r"'\s+AND\s+IF\s*\(",
        r"'\s+AND\s+CASE\s+WHEN",
    ],
}


def identify_attack_type(payload: str) -> AttackType:
    """
    识别载荷的攻击类型
    
    Args:
        payload: SQL注入载荷字符串
    
    Returns:
        AttackType 枚举值
    """
    payload_upper = payload.upper()
    
    # 优先级顺序检测
    # 1. Piggy-backed（有分号开头的额外语句）
    if re.search(r";\s*(SELECT|DELETE|INSERT|UPDATE|DROP|TRUNCATE|CREATE)\b", payload_upper):
        return AttackType.PIGGY_BACKED
    
    # 2. Time Inference（有延时函数）
    if re.search(r"(SLEEP|BENCHMARK)\s*\(", payload_upper):
        return AttackType.TIME_INFERENCE
    
    # 3. Union Query
    if re.search(r"\b(UNION|ORDER\s+BY\s+\d|GROUP\s+BY\s+\d)", payload_upper):
        return AttackType.UNION_QUERY
    
    # 4. Error Base（有错误触发函数）
    error_funcs = [
        r"CAST\s*\(", r"CONVERT\s*\(", r"SQRT\s*\(", r"LOG\d*\s*\(",
        r"MOD\s*\(", r"extractvalue\s*\(", r"updatexml\s*\(",
        r"GTID_SUBSET\s*\(", r"GTID_SUBTRACT\s*\(",
    ]
    for pattern in error_funcs:
        if re.search(pattern, payload, re.IGNORECASE):
            return AttackType.ERROR_BASE
    
    # 5. Boolean Inference
    bool_patterns = [r"SUBSTR", r"SUBSTRING", r"ASCII", r"ORD", r"LENGTH"]
    if "AND" in payload_upper:
        for p in bool_patterns:
            if p in payload_upper:
                return AttackType.BOOLEAN_INFERENCE
    
    # 6. Tautologies（OR 恒真条件）
    if re.search(r"'\s+OR\s+", payload, re.IGNORECASE):
        return AttackType.TAUTOLOGIES
    
    # 7. 简单 AND 条件也归为 Tautologies
    if re.search(r"'\s+AND\s+", payload, re.IGNORECASE):
        return AttackType.TAUTOLOGIES
    
    return AttackType.UNKNOWN


def identify_info_feature(payload: str) -> InfoFeature:
    """
    识别载荷的信息特征
    
    Args:
        payload: SQL注入载荷字符串
    
    Returns:
        InfoFeature 枚举值
    """
    # 检查占位符类型
    has_table = bool(re.search(r"\$table_\d+\$", payload))
    has_column = bool(re.search(r"\$column_t\d+_\d+\$", payload))
    has_sysinfo = bool(re.search(r"\$sysInfo\$", payload))
    
    # 判断逻辑
    if has_table or has_column:
        return InfoFeature.SPECIFIC_DB
    elif has_sysinfo:
        return InfoFeature.SYSTEM_INFO
    else:
        return InfoFeature.CONSTANT


def identify(payload_template: Dict) -> Tuple[AttackType, InfoFeature]:
    """
    识别载荷模板的攻击类型和信息特征
    
    Args:
        payload_template: 载荷模板字典，包含 'payload', 'type', 'information_features' 字段
    
    Returns:
        (AttackType, InfoFeature) 元组
    """
    # 优先使用模板中的类型信息
    if "type" in payload_template and payload_template["type"]:
        type_str = payload_template["type"]
        attack_type = AttackType(type_str) if type_str in [e.value for e in AttackType] else AttackType.UNKNOWN
    else:
        attack_type = identify_attack_type(payload_template.get("payload", ""))
    
    if "information_features" in payload_template and payload_template["information_features"]:
        feature_str = payload_template["information_features"]
        info_feature = InfoFeature(feature_str) if feature_str in [e.value for e in InfoFeature] else InfoFeature.UNKNOWN
    else:
        info_feature = identify_info_feature(payload_template.get("payload", ""))
    
    return attack_type, info_feature


# ============================================================
# 便捷函数
# ============================================================

def get_attack_type_name(attack_type: AttackType) -> str:
    """获取攻击类型的显示名称"""
    return attack_type.value


def get_info_feature_name(info_feature: InfoFeature) -> str:
    """获取信息特征的显示名称"""
    return info_feature.value
