from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import random

from utils.json_operation import read_json_file
from utils.yaml_operation import * 
from utils.LLM import *            
from utils.j2_opeartion import *   

from Attacker.generate_injection_sql import pipeline


def str_to_bool(s: str) -> bool:
    s = s.strip().lower()
    if s == "true":
        return True
    if s == "false":
        return False
    raise ValueError(f"无法将字符串 {s!r} 转为布尔值（期望 'true' 或 'false'）")

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


class Attacker:

    def __init__(
        self,
        number_of_training_sqls: int,
        rate_of_injection_sqls: float,
        cluster_list: List[str],
        normal_sqls_path: Optional[str] = None,
        raw_datas_dir: Optional[str] = None,
    ) -> None:
        """
        :param number_of_training_sqls: 默认生成的训练 SQL 总数
        :param rate_of_injection_sqls: 注入 SQL 比例（0~1）
        :param cluster_list: cluster 字符串列表，每个形如 "type||annotator||information_features||comment"
        :param normal_sqls_path: normal SQL 的 JSON 路径
        :param raw_datas_dir: 原始数据目录，包含 sql_data_with_injection_point.json 等
        """
        self.number_of_training_sqls = number_of_training_sqls
        self.rate_of_injection_sqls = rate_of_injection_sqls

        self.cluster_list = cluster_list
        if not self.cluster_list:
            raise ValueError("cluster_list 不能为空")

        # 初始时，各个聚类概率分布平均
        init_prob = 1.0 / len(cluster_list)
        self.clusters_probability_distribution: Dict[str, float] = {
            key: init_prob for key in cluster_list
        }

        # -------- 加载数据 --------
        if normal_sqls_path is None:
            raise ValueError("normal_sqls_path 不能为空")
        if raw_datas_dir is None:
            raise ValueError("raw_datas_dir 不能为空")

        self.normal_sqls: List[Dict[str, Any]] = read_json_file(normal_sqls_path)

        raw_sqls = read_json_file(f"{raw_datas_dir}/sql_data_with_injection_point.json")
        # 只留 train set
        self.train_raw_sqls: List[Dict[str, Any]] = [
            sql for sql in raw_sqls if sql.get("set") == "train"
        ]

        payloads = read_json_file(f"{raw_datas_dir}/payloads.json")
        self.train_payloads: List[Dict[str, Any]] = [
            payload for payload in payloads if payload.get("set") == "train"
        ]
        self.train_payloads_clusters: Dict[str, List[Dict[str, Any]]] = (
            self._cluster_payload_templates(self.train_payloads)
        )

        self.db_schemas = read_json_file(f"{raw_datas_dir}/schema.json")
        self.sys_schemas = read_json_file(f"{raw_datas_dir}/system_table_schema.json")
        self.system_vars = read_json_file(f"{raw_datas_dir}/system_var.json")
        self.comment_list = read_json_file(f"{raw_datas_dir}/comment_repository.json")

    def _get_single_key_of_payload_template(self, data_item: Dict[str, Any]) -> str:
        """
        将 payload 模板转换为聚类 key: type||information_features
        """
        payload_type = data_item["type"]
        information_features = data_item["information_features"]
        key = f"{payload_type}||{information_features}"
        return key

    def _cluster_payload_templates(
        self, payloads: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        按 type||information_features 将 payloads 聚类。
        """
        clusters: Dict[str, List[Dict[str, Any]]] = {}
        for item in payloads:
            key = self._get_single_key_of_payload_template(item)
            clusters.setdefault(key, []).append(item)
        return clusters

    def _sample_normal_sqls(self, k: int, replace: bool = False) -> List[Dict[str, Any]]:
        """
        从 normal_sqls 中采样 k 条。
        :param replace: False 则为无放回采样，True 则允许有放回。
        """
        total = len(self.normal_sqls)
        if total == 0:
            raise RuntimeError("normal_sqls 为空，无法采样")

        if not replace and k > total:
            raise ValueError(
                f"无放回采样 normal SQL 失败：请求 {k} 条，但仅有 {total} 条"
            )

        if replace and k > total:
            # 有放回采样
            return random.choices(self.normal_sqls, k=k)

        # 无放回采样
        return random.sample(self.normal_sqls, k=k)

    def _update_clusters_probability_distribution(
        self,
        gamma: float,
        clusters_reward_distribution: Dict[str, float],
    ) -> None:
        """
        根据 reward 更新 cluster 的概率分布，带 gamma 平滑。
        当所有 reward 为 0 时，退化为均匀分布。
        """
        # 保证所有 cluster 都有 reward（缺失视作 0）
        rewards = {
            key: float(clusters_reward_distribution.get(key, 0.0))
            for key in self.cluster_list
        }

        all_reward = sum(rewards.values())

        if all_reward <= 0:
            # 全部 reward 为 0 -> 均匀分布
            uniform_prob = 1.0 / len(self.cluster_list)
            self.clusters_probability_distribution = {
                k: uniform_prob for k in self.cluster_list
            }
            return

        new_dist: Dict[str, float] = {}
        n = len(self.cluster_list)
        for key in self.cluster_list:
            reward = rewards[key]
            prob = (1.0 - gamma) * (reward / all_reward) + gamma / n
            new_dist[key] = prob

        # 归一化以避免浮点误差累积
        s = sum(new_dist.values())
        if s <= 0:
            # 理论上不会发生，兜底一下
            uniform_prob = 1.0 / n
            self.clusters_probability_distribution = {
                k: uniform_prob for k in self.cluster_list
            }
        else:
            self.clusters_probability_distribution = {
                k: v / s for k, v in new_dist.items()
            }

    def _select_clusters(self, strategy: str, k: int) -> List[str]:
        """
        按策略选出需要使用的 cluster：
        - "top_k": 根据当前概率，从大到小取前 k 个；
        - "by_probability": 按概率分布做无放回随机采样 k 个。
        """
        if k <= 0:
            raise ValueError(f"_select_clusters: k 必须 > 0，当前为 {k}")
        if k > len(self.clusters_probability_distribution):
            raise ValueError(
                f"_select_clusters: k={k} 超过了 cluster 数量 {len(self.clusters_probability_distribution)}"
            )

        if strategy == "top_k":
            sorted_items = sorted(
                self.clusters_probability_distribution.items(),
                key=lambda x: x[1],
                reverse=True,
            )
            return [key for key, _ in sorted_items[:k]]

        if strategy == "by_probability":
            keys = np.array(list(self.clusters_probability_distribution.keys()))
            probs_arr = np.array(
                list(self.clusters_probability_distribution.values()),
                dtype=float,
            )

            # 归一化概率，避免浮点误差
            total = probs_arr.sum()
            if total <= 0:
                # 退化为均匀分布
                probs_arr = np.full_like(probs_arr, 1.0 / len(probs_arr))
            else:
                probs_arr = probs_arr / total

            rng = np.random.default_rng(None)
            indices = rng.choice(len(keys), size=k, replace=False, p=probs_arr)
            return keys[indices].tolist()

        raise ValueError(f"_select_clusters: 不支持的 strategy: {strategy!r}")

    def _get_raw_data_by_cluster_feature(
        self,
        cluster: str,
    ) -> tuple[Dict[str, Any], Dict[str, Any], int]:
        """
        根据 cluster 字符串，从 train_raw_sqls 和 train_payloads_clusters 中
        各选出一条样本，并返回 (sql_example, payload_example, comment_rate)。
        """
        cluster_key = ClusterKey.from_str(cluster)

        # 1. 选 SQL
        sql_candidates = [
            sql
            for sql in self.train_raw_sqls
            if sql.get("annotator") == cluster_key.annotator
        ]
        if not sql_candidates:
            raise RuntimeError(
                f"_get_raw_data_by_cluster_feature: "
                f"找不到 annotator={cluster_key.annotator} 的 train_raw_sqls，cluster={cluster!r}"
            )
        sql_example = random.choice(sql_candidates)

        # 2. 选 payload
        payload_key = cluster_key.payload_cluster_key()
        payload_candidates = self.train_payloads_clusters.get(payload_key)
        if payload_candidates is None or not payload_candidates:
            raise RuntimeError(
                f"_get_raw_data_by_cluster_feature: "
                f"找不到或为空的 payload cluster: {payload_key!r}, cluster={cluster!r}"
            )
        payload_example = random.choice(payload_candidates)

        # 3. comment -> comment_rate
        comment_rate = 1 if cluster_key.comment else 0

        return sql_example, payload_example, comment_rate

    def _modify_raw_payload_template(self, payload_template):
        pass
    
    def generate_training_sqls(
        self,
        gamma: float,
        clusters_reward_distribution: Dict[str, float],
        strategy: str,
        k: int,
        expected_example_num: Optional[int] = None,
    ) -> List[Any]:
        """
        生成训练用 SQL 列表（包含注入 SQL 与正常 SQL）。

        :param gamma: 概率分布更新的平滑系数 (0~1)。
        :param clusters_reward_distribution: 每个 cluster 的 reward。
        :param strategy: cluster 选择策略：'top_k' 或 'by_probability'。
        :param k: 每轮选择的 cluster 数。
        :param expected_example_num: 期望总样本数；默认为 self.number_of_training_sqls。
        :return: 一个乱序的 SQL 列表（注入 SQL 与正常 SQL 混合）。
        """
        expected_example_num = (
            self.number_of_training_sqls
            if expected_example_num is None
            else expected_example_num
        )
        if expected_example_num <= 0:
            raise ValueError(
                f"expected_example_num 必须 > 0，当前为 {expected_example_num}"
            )

        # 计算需要的注入 SQL 与 normal SQL 数量
        expected_injection_num = int(expected_example_num * self.rate_of_injection_sqls)
        expected_normal_num = expected_example_num - expected_injection_num

        # 更新 cluster 概率分布
        self._update_clusters_probability_distribution(
            gamma=gamma,
            clusters_reward_distribution=clusters_reward_distribution,
        )

        # 选出目标 clusters
        target_clusters = self._select_clusters(strategy=strategy, k=k)

        injection_sql_examples: List[Any] = []
        count = 0

        # 不断轮询这些 cluster 生成注入 SQL，直到数量满足要求
        while count < expected_injection_num:
            for cluster in target_clusters:
                sql_example, payload_example, comment_rate = (
                    self._get_raw_data_by_cluster_feature(cluster=cluster)
                )
                injection_sql_example = pipeline(
                    sql_example=sql_example,
                    payload_template=payload_example,
                    db_schemas=self.db_schemas,
                    sys_schemas=self.sys_schemas,
                    system_vars=self.system_vars,
                    comment_list=self.comment_list,
                    comment_rate=comment_rate,
                )
                if injection_sql_example is not None:
                    injection_sql_examples.append(injection_sql_example)
                    count += 1
                    if count >= expected_injection_num:
                        break

        # 采样 normal SQL
        normal_sql_examples = self._sample_normal_sqls(
            k=expected_normal_num,
            replace=False,
        )

        # 合并并打乱
        training_sqls = injection_sql_examples + normal_sql_examples
        random.shuffle(training_sqls)
        return training_sqls

        
    
