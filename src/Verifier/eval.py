from utils.json_operation import read_jsonl_file
from dataclasses import dataclass
from typing import Dict, List, Any, Optional



def get_single_key_of_injection_sql(data_item: Dict[str, Any]) -> str:
    """
    按攻击类型 + 标注方式 + 信息特征 + 注释情况 聚类。
    注意：这里直接使用结果文件中的四个字段。
    """
    attack_type = data_item["type"]
    annotator = data_item["annotator"]
    information_features = data_item["information_features"]
    comment = data_item["comment"]
    key = f"{attack_type}||{annotator}||{information_features}||{comment}"
    return key

def cluster_injection_sqls(datas: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    将数据按 cluster key 分组：
        { cluster_key: [item1, item2, ...], ... }
    """
    clusters: Dict[str, List[Dict[str, Any]]] = {}
    for item in datas:
        key = get_single_key_of_injection_sql(item)
        clusters.setdefault(key, []).append(item)
    return clusters

@dataclass
class ClusterStat:
    acc: float
    total: int
    correct: int

def compute_cluster_reward(clusters: Dict[str, List[Dict[str, Any]]]) -> Dict[str, ClusterStat]:
    """
    计算每个 cluster 的 ACC:
        ACC = #correct / #total

    返回:
        { key: ClusterStat(acc, total, correct) }
    """
    stats: Dict[str, ClusterStat] = {}

    for key, items in clusters.items():
        total = len(items)
        correct = sum(1 for item in items if item.get("is_correct"))
        acc = correct / total if total > 0 else 0.0
        stats[key] = ClusterStat(acc=acc, total=total, correct=correct)

    return stats
