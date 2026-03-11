from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import random
from pathlib import Path

from utils.json_operation import read_json_file
from utils.LLM import LLM
from utils.cluster import *
from utils.yaml_operation import load_yaml_to_dict
import os

from .generate_injection_sql import pipeline

# 导入 Payload Mutation 模块（项目内置）
from .payload_mutation import PayloadMutator, MutationMemory


class Attacker:

    def __init__(
        self,
        number_of_training_sqls: int,
        cluster_list: List[str],
        normal_sqls_path: Optional[str] = None,
        raw_datas_dir: Optional[str] = None,
        enable_payload_mutation: bool = True,
        mutation_model: Optional[str] = None,
    ) -> None:
        self.cluster_list = cluster_list
        if not self.cluster_list:
            raise ValueError("cluster_list 不能为空")

        init_prob = 1.0 / len(cluster_list)
        self.clusters_probability_distribution: Dict[str, float] = {
            key: init_prob for key in cluster_list
        }
        self.number_of_training_sqls = number_of_training_sqls
        self.rate_of_injection_sqls = 1-(10*self.clusters_probability_distribution['normal||normal||normal||normal'])
        
        if normal_sqls_path is None:
            raise ValueError("normal_sqls_path 不能为空")
        if raw_datas_dir is None:
            raise ValueError("raw_datas_dir 不能为空")

        self.normal_sqls: List[Dict[str, Any]] = read_json_file(normal_sqls_path)

        raw_sqls = read_json_file(f"{raw_datas_dir}/sql_data_with_injection_point.json")
        self.train_raw_sqls: List[Dict[str, Any]] = [
            sql for sql in raw_sqls if sql.get("set") == "train"
        ]

        payloads = read_json_file(f"{raw_datas_dir}/payloads.json")
        self.train_payloads: List[Dict[str, Any]] = [
            payload for payload in payloads if payload.get("set") == "train"
        ]
        self.train_payloads_clusters: Dict[str, List[Dict[str, Any]]] = (
            cluster_payload_templates(self.train_payloads)
        )

        self.db_schemas = read_json_file(f"{raw_datas_dir}/schema.json")
        self.sys_schemas = read_json_file(f"{raw_datas_dir}/system_table_schema.json")
        self.system_vars = read_json_file(f"{raw_datas_dir}/system_var.json")
        self.comment_list = read_json_file(f"{raw_datas_dir}/comment_repository.json")
        
        # 初始化 Payload Mutation 模块
        self.enable_payload_mutation = enable_payload_mutation
        self.payload_mutator: Optional[PayloadMutator] = None
        self.mutation_memory: Optional[MutationMemory] = None
        
        # 🆕 维护每轮变异成功的 payload 列表
        self.mutated_payloads: List[Dict[str, Any]] = []
        
        if enable_payload_mutation:
            self._init_payload_mutator(mutation_model)

    def _sample_normal_sqls(self, k: int, replace: bool = False) -> List[Dict[str, Any]]:
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

    def _update_clusters_probability_distribution(self, gamma: float, clusters_weight_distribution: Dict[str, float],) -> None:
        weights = {
            key: float(clusters_weight_distribution.get(key, 0.0))
            for key in self.cluster_list
        }

        all_weight = sum(weights.values())

        if all_weight <= 0:
            uniform_prob = 1.0 / len(self.cluster_list)
            self.clusters_probability_distribution = {
                k: uniform_prob for k in self.cluster_list
            }
            return

        new_dist: Dict[str, float] = {}
        n = len(self.cluster_list)
        for key in self.cluster_list:
            weight = weights[key]
            prob = (1.0 - gamma) * (weight / all_weight) + gamma / n
            new_dist[key] = prob
        s = sum(new_dist.values())
        if s <= 0:
            uniform_prob = 1.0 / n
            self.clusters_probability_distribution = {
                k: uniform_prob for k in self.cluster_list
            }
        else:
            self.clusters_probability_distribution = {
                k: v / s for k, v in new_dist.items()
            }

    def _select_clusters(self, strategy="by_probability", k=10) -> List[str]:
        clusters_probability_distribution = {k: v for k, v in self.clusters_probability_distribution.items() if k != "normal||normal||normal||normal"}
        if k <= 0:
            raise ValueError(f"_select_clusters: k 必须 > 0，当前为 {k}")
        if k > len(clusters_probability_distribution):
            raise ValueError(
                f"_select_clusters: k={k} 超过了 cluster 数量 {len(clusters_probability_distribution)}"
            )

        if strategy == "top_k":
            sorted_items = sorted(
                clusters_probability_distribution.items(),
                key=lambda x: x[1],
                reverse=True,
            )
            return [key for key, _ in sorted_items[:k]]

        if strategy == "by_probability":
            keys = np.array(list(clusters_probability_distribution.keys()))
            probs_arr = np.array(
                list(clusters_probability_distribution.values()),
                dtype=float,
            )

            total = probs_arr.sum()
            if total <= 0:
                probs_arr = np.full_like(probs_arr, 1.0 / len(probs_arr))
            else:
                probs_arr = probs_arr / total

            rng = np.random.default_rng(None)
            indices = rng.choice(len(keys), size=k, replace=False, p=probs_arr)
            return keys[indices].tolist()

        raise ValueError(f"_select_clusters: 不支持的 strategy: {strategy!r}")

    def _get_raw_data_by_cluster_feature(self,cluster: str,) -> tuple[Dict[str, Any], Dict[str, Any], int]:
        cluster_key = ClusterKey.from_str(cluster)

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

        payload_key = cluster_key.payload_cluster_key()
        payload_candidates = self.train_payloads_clusters.get(payload_key)
        if payload_candidates is None or not payload_candidates:
            raise RuntimeError(
                f"_get_raw_data_by_cluster_feature: "
                f"找不到或为空的 payload cluster: {payload_key!r}, cluster={cluster!r}"
            )
        payload_example = random.choice(payload_candidates)

        comment_flag = cluster_key.comment

        return sql_example, payload_example, comment_flag

    def _init_payload_mutator(self, mutation_model: Optional[str] = None) -> None:
        """初始化 Payload 变异器"""
        try:
            # 加载 GPT 配置
            project_root = Path(__file__).resolve().parents[2]
            gpt_config_path = project_root / "config" / "gpt_config.yaml"
            gpt_config = load_yaml_to_dict(str(gpt_config_path))
            
            # 初始化 LLM
            llm = LLM(
                api_key=gpt_config['api_key'],
                base_url=gpt_config.get('base_url', None)
            )
            
            # 使用配置中的模型或者传入的模型
            model = mutation_model or gpt_config.get('model')
            
            # 初始化 Memory 和 Mutator
            self.mutation_memory = MutationMemory()
            self.payload_mutator = PayloadMutator(llm, model, self.mutation_memory)
            
            print(f"✓ Payload Mutator 初始化成功，使用模型: {model}")
            
        except Exception as e:
            print(f"⚠️ Payload Mutator 初始化失败: {e}")
            print("  将禁用 payload 变异功能，使用原始模板")
            self.enable_payload_mutation = False
            self.payload_mutator = None
            self.mutation_memory = None
    
    def _modify_raw_payload_template(
        self, 
        payload_template: Dict[str, Any],
        modify_probability: float = 0.5,
    ) -> Dict[str, Any]:
        """
        使用 LLM 对 payload 模板进行变异，生成更丰富的训练数据
        
        Args:
            payload_template: 原始 payload 模板字典，包含 'payload', 'type', 'information_features' 等字段
            modify_probability: 进行变异的概率 (0-1)，默认 0.5
            
        Returns:
            变异后的 payload 模板（如果未变异或变异失败则返回原模板的副本）
        """
        # 如果未启用变异或 mutator 未初始化，直接返回原模板
        if not self.enable_payload_mutation or self.payload_mutator is None:
            return payload_template.copy()
        
        # 概率决定是否进行变异
        if random.random() > modify_probability:
            return payload_template.copy()
        
        try:
            # 调用 PayloadMutator 进行变异
            mutation_result = self.payload_mutator.mutate(payload_template)
            
            if mutation_result is not None:
                # 变异成功，构建新的模板
                modified_template = payload_template.copy()
                modified_template['payload'] = mutation_result['payload']
                # 保留原始模板信息用于调试
                modified_template['_original_payload'] = payload_template['payload']
                modified_template['_mutation_type'] = mutation_result.get('mutation_type', 'unknown')
                
                # 🆕 使用 LLM 推断的 expected_types（如果有的话）
                # 这是独立于变异的第二个任务，确保类型与变异后的 payload 语义一致
                if mutation_result.get('expected_types') is not None:
                    modified_template['expected_types'] = mutation_result['expected_types']
                    modified_template['_expected_types_inferred'] = True
                else:
                    # 如果 LLM 未能推断类型，保留原始类型（可能不准确）
                    modified_template['_expected_types_inferred'] = False
                
                return modified_template
            else:
                # 变异失败，返回原模板
                return payload_template.copy()
                
        except Exception as e:
            # 出现异常，返回原模板
            print(f"⚠️ Payload 变异异常: {e}")
            return payload_template.copy()
    
    def get_mutation_stats(self) -> Optional[Dict]:
        """获取 Payload 变异统计信息"""
        if self.payload_mutator is not None:
            return self.payload_mutator.get_stats()
        return None
    
    def get_memory_stats(self) -> Optional[Dict]:
        """获取变异记忆统计信息"""
        if self.mutation_memory is not None:
            return self.mutation_memory.get_stats()
        return None
    
    def get_mutated_payloads(self) -> List[Dict[str, Any]]:
        """获取当前轮次变异成功的 payload 列表"""
        return self.mutated_payloads.copy()
    
    def clear_mutated_payloads(self) -> None:
        """清空变异 payload 列表（每轮开始前调用）"""
        self.mutated_payloads = []
    
    def generate_training_sqls(
        self, 
        gamma: float, 
        clusters_weight_distribution: Dict[str, float], 
        strategy: str, 
        k: int, 
        expected_example_num: Optional[int] = None,
        modify_payload_prob: float = 0.5,
    ) -> List[Any]:
        """
        生成训练用的 SQL 样本
        
        Args:
            gamma: 概率分布更新的平滑系数
            clusters_weight_distribution: 各 cluster 的权重分布
            strategy: 采样策略 ("by_probability" 或 "top_k")
            k: 选择的 cluster 数量
            expected_example_num: 期望生成的样本数量
            modify_payload_prob: Payload 变异概率 (0-1)，默认 0.5
            
        Returns:
            训练 SQL 列表和 cluster 概率分布
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
        
        self._update_clusters_probability_distribution(
            gamma=gamma,
            clusters_weight_distribution=clusters_weight_distribution,
        )
        
        self.rate_of_injection_sqls = 1-(10*self.clusters_probability_distribution['normal||normal||normal||normal'])
        expected_injection_num = int(expected_example_num * self.rate_of_injection_sqls)
        expected_normal_num = expected_example_num - expected_injection_num

        
        target_clusters = self._select_clusters(strategy=strategy, k=k)
        print(f"选中的 clusters: {target_clusters}")

        injection_sql_examples: List[Any] = []
        count = 0
        mutation_count = 0  # 统计成功变异的数量
        
        # 🆕 每轮开始前清空变异 payload 列表
        self.clear_mutated_payloads()

        while count < expected_injection_num:
            for cluster in target_clusters:
                sql_example, payload_example, comment_flag = (
                    self._get_raw_data_by_cluster_feature(cluster=cluster)
                )
                
                # 🔥 使用 LLM 对 payload 模板进行变异
                modified_payload = self._modify_raw_payload_template(
                    payload_template=payload_example,
                    modify_probability=modify_payload_prob,
                )
                
                # 统计变异情况，并记录变异成功的 payload
                if modified_payload.get('_mutation_type') is not None:
                    mutation_count += 1
                    # 🆕 记录变异成功的 payload 完整信息
                    self.mutated_payloads.append({
                        # === 变异结果 ===
                        "original_payload": modified_payload.get('_original_payload'),
                        "mutated_payload": modified_payload.get('payload'),
                        "mutation_type": modified_payload.get('_mutation_type'),
                        
                        # === 原始 Payload 模板信息 ===
                        "attack_type": payload_example.get('type'),
                        "information_features": payload_example.get('information_features'),
                        "original_expected_types": payload_example.get('expected_types'),
                        
                        # === 🆕 推断的 expected_types ===
                        "inferred_expected_types": modified_payload.get('expected_types'),
                        "expected_types_inferred": modified_payload.get('_expected_types_inferred', False),
                        
                        # === 原始 SQL 样本信息 ===
                        "sql_db": sql_example.get('db'),
                        "sql_raw": sql_example.get('sql_raw'),
                        "sql_with_injection_point": sql_example.get('sql'),
                        "sql_query_columns": sql_example.get('query_columns'),
                        "sql_source": sql_example.get('source'),
                        "sql_annotator": sql_example.get('annotator'),
                        
                        # === 上下文信息 ===
                        "cluster": cluster,
                        "comment_flag": comment_flag,
                    })
                
                injection_sql_example = pipeline(
                    sql_example=sql_example,
                    payload_template=modified_payload,  # 使用变异后的 payload
                    db_schemas=self.db_schemas,
                    sys_schemas=self.sys_schemas,
                    system_vars=self.system_vars,
                    comment_list=self.comment_list,
                    comment_flag=comment_flag,
                )
                if injection_sql_example is not None:
                    injection_sql_examples.append(injection_sql_example)
                    count += 1
                if count >= expected_injection_num:
                    break
        
        # 打印变异统计
        if self.enable_payload_mutation:
            print(f"📊 Payload 变异统计: {mutation_count}/{count} 个样本使用了变异后的 payload")
            if self.payload_mutator is not None:
                stats = self.payload_mutator.get_stats()
                print(f"   - 变异成功率: {stats['success_rate']:.2%}")
                print(f"   - 总尝试: {stats['total_attempts']}, 成功: {stats['successful']}, 失败: {stats['failed']}, 重复: {stats['duplicates']}")
                print(f"   - Expected Types 推断: {stats['types_inferred']} 个")
                if 'types_inferrer_stats' in stats:
                    ts = stats['types_inferrer_stats']
                    print(f"   - 推断详情: LLM成功: {ts['llm_success']}, 启发式回退: {ts['fallback_used']}")

        normal_sql_examples = self._sample_normal_sqls(
            k=expected_normal_num,
            replace=False,
        )

        training_sqls = injection_sql_examples + normal_sql_examples
        random.shuffle(training_sqls)
        return training_sqls, self.clusters_probability_distribution

        
def main():
    project_root = os.path.dirname(os.path.abspath(__file__))

    normal_sqls_path = r"data\raw_datas_for_generation\normal_sqls.json"
    raw_datas_dir = r"data\raw_datas_for_generation"
    
    cluster_list = cluster_injection_sqls(read_json_file(r"data\temp_data\test_sqls.json")).keys()

    attacker = Attacker(
        number_of_training_sqls=50,
        cluster_list=cluster_list,
        normal_sqls_path=normal_sqls_path,
        raw_datas_dir=raw_datas_dir,
    )

    clusters_weight_distribution = {'Time base inference attack||False||system information||False': 1.0, 'Piggy-backed queries attacks||False||specific database||False': 1.0, 'Tautologies attack||True||system information||False': 1.0, 'Boolean base inference attack||False||system information||False': 1.0, 'Time base inference attack||True||constant||False': 1.0, 'normal||normal||normal||normal': 1.4041449927044993, 'Union-query attack||True||constant||False': 1.0, 'Time base inference attack||False||specific database||False': 1.0, 'Union-query attack||True||system information||False': 1.0, 'Piggy-backed queries attacks||True||specific database||False': 1.0, 'Error base attack||True||specific database||True': 1.1460985809492783, 'Error base attack||True||specific database||False': 1.0, 'Time base inference attack||True||specific database||True': 1.2840254166877414, 'Tautologies attack||True||constant||False': 1.0, 'Union-query attack||True||specific database||False': 1.0, 'Union-query attack||True||constant||True': 1.0465034351948703, 'Union-query attack||False||specific database||False': 1.0, 'Error base attack||False||specific database||False': 1.0, 'Union-query attack||True||specific database||True': 1.3498588075760032, 'Boolean base inference attack||True||system information||True': 1.16631144044593, 'Error base attack||True||system information||True': 1.2840254166877414, 'Tautologies attack||False||constant||False': 1.0, 'Boolean base inference attack||True||specific database||False': 1.0, 'Tautologies attack||False||system information||False': 1.0, 'Boolean base inference attack||True||system information||False': 1.0, 'Error base attack||False||system information||False': 1.0, 'Error base attack||True||constant||True': 1.128274703809024, 'Boolean base inference attack||True||specific database||True': 1.181360412865646, 'Error base attack||False||constant||False': 1.0219771469591552, 'Tautologies attack||True||specific database||False': 1.0, 'Union-query attack||False||system information||False': 1.0, 'Time base inference attack||True||constant||True': 1.2214027581601699, 'Boolean base inference attack||False||specific database||False': 1.0, 'Error base attack||True||system information||False': 1.0, 'Union-query attack||False||constant||False': 1.1535649948951077, 'Piggy-backed queries attacks||True||system information||False': 1.0, 'Time base inference attack||True||specific database||False': 1.0, 'Tautologies attack||True||specific database||True': 1.1460985809492783, 'Piggy-backed queries attacks||True||system information||True': 1.1223050103450638, 'Tautologies attack||True||constant||True': 1.0869040495212288, 'Tautologies attack||True||system information||True': 1.1710429205438226, 'Time base inference attack||False||constant||False': 1.0, 'Piggy-backed queries attacks||True||specific database||True': 1.161834242728283, 'Piggy-backed queries attacks||False||system information||False': 1.0, 'Error base attack||True||constant||False': 1.0, 'Time base inference attack||True||system information||False': 1.0, 'Time base inference attack||True||system information||True': 1.0644944589178593, 'Union-query attack||True||system information||True': 1.0, 'Tautologies attack||False||specific database||False': 1.0}

    gamma = 0.2
    strategy = "by_probability"
    k = 10 

    training_sqls = attacker.generate_training_sqls(
        gamma=gamma,
        clusters_weight_distribution=clusters_weight_distribution,
        strategy=strategy,
        k=k,
        expected_example_num=20,   # 也可以不传，默认使用 number_of_training_sqls
    )

    print(f"共生成 {len(training_sqls)} 条训练 SQL（包含注入 + 正常）")
    for i, item in enumerate(training_sqls[:20], start=1):
        print(f"\n=== 示例 {i} ===")
        if isinstance(item, dict):
            print(item.get("sql", item))
            print(f"标签: {'benign' if item.get('label', True) else 'malicious'}")
        else:
            print(item)


if __name__ == "__main__":
    main()
