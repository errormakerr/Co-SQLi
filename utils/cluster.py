from dataclasses import dataclass

def str_to_bool(s: str) -> bool:
    s = s.strip().lower()
    if s == "true":
        return True
    if s == "false":
        return False
    raise ValueError(f"无法将字符串 {s!r} 转为布尔值（期望 'true' 或 'false'）")


def get_single_key_of_payload_template(data_item):
    type = data_item['type']
    information_features = data_item['information_features']
    key = f"{type}||{information_features}"
    return key

def cluster_payload_templates(datas):
    clusters = dict()
    for item in datas:
        key = get_single_key_of_payload_template(item)
        if key not in clusters:
            clusters[key] = []
        clusters[key].append(item)
    
    return clusters

def get_single_key_of_injection_sql(data_item):
    if not data_item['label']:
        type = data_item['payload_template']['type']
        annotator = data_item['original_sql']['annotator']
        information_features = data_item['payload_template']['information_features']
        comment = data_item.get('comment')
        key = f"{type}||{annotator}||{information_features}||{comment}"
    else:
        key = "normal||normal||normal||normal"
    return key

def cluster_injection_sqls(datas):
    clusters = dict()
    for item in datas:
        key = get_single_key_of_injection_sql(item)
        if key not in clusters:
            clusters[key] = []
        clusters[key].append(item)
    
    return clusters


@dataclass(frozen=True)
class ClusterKey:
    payload_type: str
    annotator: bool
    information_features: str
    comment: bool

    @classmethod
    def from_str(cls, s: str) -> "ClusterKey":
        parts = s.split("||")
        if len(parts) != 4:
            raise ValueError(
                f"ClusterKey.from_str: 非法 cluster key {s!r}，"
                f"期望 4 段（type||annotator||information_features||comment）"
            )
        payload_type, annotator_str, info_feat, comment_str = parts
        return cls(
            payload_type=payload_type,
            annotator=str_to_bool(annotator_str),
            information_features=info_feat,
            comment=str_to_bool(comment_str),
        )

    def payload_cluster_key(self) -> str:
        """用于在 payload 聚类字典中取值的 key: type||information_features"""
        return f"{self.payload_type}||{self.information_features}"
