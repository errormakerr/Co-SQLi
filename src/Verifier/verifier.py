from __future__ import annotations

import os
from typing import Dict,Optional

from utils.json_operation import read_jsonl_file
from eval import ClusterStat, cluster_injection_sqls, compute_cluster_reward



class Verifier:
    def __init__(
        self,
        save_dir: Optional[str] = None,
    ):
        """
        :param results_file: defender 的预测结果 jsonl 文件路径
        :param save_dir: 可选，保存 cluster 统计与 reward 的目录
        """
        self.save_dir = save_dir

        self._cluster_stats: Dict[str, ClusterStat] = {}
        self._cluster_rewards: Dict[str, float] = {}
        self._cluster_weight: Dict[str, float] = {}

    # ----- 对外主流程 -----

    def get_reward(self, results_file) -> Dict[str, float]:
        datas = read_jsonl_file(results_file)
        print(f"[Verifier] 读取到 {len(datas)} 条样本。")

        clusters = cluster_injection_sqls(datas)
        self._cluster_stats = compute_cluster_reward(clusters)
        self._cluster_rewards = {
            key: 1.0 - stat.acc for key, stat in self._cluster_stats.items()
        }

        return self._cluster_rewards
    
    def get_weight(self, ):
        pass
    


# ========= 一个简单的 main 示例 =========

def main():
    results_file = r"D:\project\SQLI-main\SQLI-main\results.jsonl"
    save_dir = r"D:\project\SQLI-main\SQLI-main\verifier_output"

    verifier = Verifier(results_file=results_file, save_dir=save_dir)
    clusters_reward_distribution = verifier.evaluate()

    # 之后可以把 clusters_reward_distribution 直接传给 Attacker:
    # attacker.generate_training_sqls(
    #     gamma=0.2,
    #     clusters_reward_distribution=clusters_reward_distribution,
    #     strategy="by_probability",
    #     k=10,
    #     expected_example_num=200,
    # )


if __name__ == "__main__":
    main()
