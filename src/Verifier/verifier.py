from __future__ import annotations

import os
from typing import Dict,Optional

from utils.json_operation import read_jsonl_file, read_json_file
from typing import Any, Dict, List, Optional
from utils.cluster import *
import math
from .eval import cluster_results, compute_cluster_acc


class Verifier:
    def __init__(self,cluster_list: List[str],):
        """
        :param results_file: defender 的预测结果 jsonl 文件路径
        :param save_dir: 可选，保存 cluster 统计与 reward 的目录
        """
  
        self.cluster_list = cluster_list
        self.cluster_rewards: Dict[str, float] = {
            key : 0 for key in cluster_list
        }
        self.cluster_weight: Dict[str, float] = {
            key : 1 for key in cluster_list
        }
        
    def get_weights(self) -> Dict[str, float]:
        return self.cluster_weight
    
    def set_weights(self, weights: Dict[str, float]):
        self.cluster_weight = weights

    def update_reward(self, results):

        clusters = cluster_results(results)
        cluster_stats = compute_cluster_acc(clusters)
        new_cluster_rewards = {
            key: 1.0 - stat.acc for key, stat in cluster_stats.items()
        }
        for key, reward in new_cluster_rewards.items():
            self.cluster_rewards[key] = reward

    
    def update_weight(self, gamma, cluster_probability_distribution):
        for key, weight in self.cluster_weight.items():
            self.cluster_weight[key] = weight * math.exp(gamma/len(self.cluster_list) * self.cluster_rewards[key]/cluster_probability_distribution[key])



# ========= 一个简单的 main 示例 =========

def main():
    results_file = r"/home/panhao/model/temp_data/round_0/inference/results.jsonl"
    results = read_jsonl_file(results_file)
    cluster_list = cluster_injection_sqls(read_json_file(r"/home/panhao/project/SQLI/data/benchmark/test_sqls.json")).keys()
    
    init_prob = 1.0 / len(cluster_list)
    clusters_probability_distribution = {key: init_prob for key in cluster_list}
    print(len(cluster_list))
    verifier = Verifier(cluster_list=cluster_list)
    # for key, reward in verifier.cluster_rewards.items():
    #     print(key, reward)
    # print("\n")
    # for key, weight in verifier.cluster_weight.items():
    #     print(key, weight)
    # print("\n")
        
    verifier.update_reward(results=results)
    for key, reward in verifier.cluster_rewards.items():
        print(key, reward)
    print("\n")
    verifier.update_weight(gamma=0.5, cluster_probability_distribution=clusters_probability_distribution)
    for key, weight in verifier.cluster_weight.items():
        print(key, weight)
    print("\n")
    print(verifier.cluster_weight)
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
