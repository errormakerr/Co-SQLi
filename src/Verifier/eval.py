from utils.json_operation import read_jsonl_file
from typing import Dict, List, Any
from dataclasses import dataclass

def str2bool(s: str) -> bool:
    v = s.strip().lower()
    if v == "true":
        return True
    if v == "false":
        return False
    raise ValueError(f"Invalid boolean string: {s!r}")


@dataclass
class ClusterStat:
    acc: float
    total: int
    correct: int

def get_single_key_of_result(data_item):
    if not data_item['label']:
        type = data_item['type']
        annotator = str2bool(data_item['annotator']) if isinstance(data_item.get('annotator'), str) else data_item['annotator']
        information_features = data_item['information_features'] 
        comment = str2bool(data_item.get('comment')) if isinstance(data_item.get('comment'), str) else data_item.get('comment')
        key = f"{type}||{annotator}||{information_features}||{comment}"
    else:
        key = "normal||normal||normal||normal"
    return key

def cluster_results(datas):
    clusters = dict()
    for item in datas:
        key = get_single_key_of_result(item)
        if key not in clusters:
            clusters[key] = []
        clusters[key].append(item)
    
    return clusters
    

def compute_cluster_acc(clusters: Dict[str, List[Dict[str, Any]]]) -> Dict[str, ClusterStat]:
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


def main():
    file_path = r"data\temp_data\results.jsonl"
    datas = read_jsonl_file(file_path)
    if not datas:
        print("没有读取到任何数据，检查文件路径或内容。")
        return
    clusters = cluster_results(datas)
    print(f"共得到 {len(clusters)} 个聚类。")
    stats = compute_cluster_acc(clusters)
    print("\n==== 每个聚类的统计信息 ====")
    for key, stat in stats.items():
        print(f"{key}:   ACC={stat.acc:.3f}")# , total={stat.total}, correct={stat.correct}




if __name__ == "__main__":
    main()