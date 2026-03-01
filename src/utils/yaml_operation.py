import yaml
from typing import Any, Dict


def load_yaml_to_dict(file_path: str) -> Dict[str, Any]:
    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    # 一般情况下 YAML 顶层是 dict，如果不是，你可以按需处理
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise TypeError(f"YAML 顶层不是字典类型，而是: {type(data)}")
    
    return data


# 示例调用
if __name__ == "__main__":
    config = load_yaml_to_dict("config.yaml")
    print(config)
    print(config.get("database", {}))
