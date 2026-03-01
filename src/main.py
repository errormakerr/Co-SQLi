"""SQLI 项目主入口：对抗性训练循环（攻击-防御-验证）"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from Attacker.Attacker import Attacker
from CoT_producer.CoT_producer import CoT_producer
from Defender.defender import Defender
from Verifier.verifier import Verifier
from utils.cluster import cluster_injection_sqls
from utils.json_operation import read_json_file, read_jsonl_file, write_jsonl_file


# ==================== 配置常量 ====================
@dataclass
class ProjectPaths:
    """项目路径配置"""
    project_root: Path
    raw_datas_dir: Path
    benchmark_dir: Path
    temp_datas_dir: Path
    config_dir: Path
    base_model_path: Path
    
    @classmethod
    def create(cls) -> "ProjectPaths":
        """创建默认路径配置"""
        project_root = Path(__file__).resolve().parents[1]
        return cls(
            project_root=project_root,
            raw_datas_dir=project_root / "data" / "raw_datas_for_generation",
            benchmark_dir=project_root / "data" / "benchmark",
            temp_datas_dir=Path("/home/panhao/model/temp_data/Qwen2.5-Coder-1.5B-Instruct_without_modify"),
            config_dir=project_root / "config",
            base_model_path=Path("/home/panhao/model/base_model/Qwen2.5-Coder-1.5B-Instruct"),
        )


# ==================== 训练参数 ====================
NUM_ROUNDS = 8
NUM_TRAINING_SQLS = 300
ATTACKER_GAMMA = 0.7
VERIFIER_GAMMA = 0.3
ATTACKER_STRATEGY = "by_probability"  # 前期的默认策略
ATTACKER_STRATEGY_TOP_K = "top_k"     # 后期使用的策略
ATTACKER_K = 8
# 策略切换点：前 PROBABILITY_ROUNDS 轮使用概率采样，之后使用 top-k 采样
PROBABILITY_ROUNDS = NUM_ROUNDS - 2  # 前6轮使用概率采样，后2轮使用 top-k


# ==================== 工具函数 ====================
def delete_folder_if_exists(folder_path: str) -> None:
    """安全删除文件夹（如果存在）"""
    if not os.path.exists(folder_path):
        return
    
    if not os.path.isdir(folder_path):
        print(f"警告: '{folder_path}' 是文件而非文件夹，跳过删除")
        return
    
    try:
        shutil.rmtree(folder_path)
        print(f"✓ 已删除文件夹: {folder_path}")
    except OSError as e:
        print(f"✗ 删除失败: {e.strerror}")
    except Exception as e:
        print(f"✗ 发生未知错误: {e}")


# ==================== 核心逻辑 ====================
def initialize_components(paths: ProjectPaths) -> Tuple[Attacker, CoT_producer, Defender, Verifier]:
    """初始化所有组件"""
    # 加载配置
    test_sqls_path = paths.benchmark_dir / "test_sqls.json"
    normal_sqls_path = paths.raw_datas_dir / "normal_sqls.json"
    valid_datas_path = paths.benchmark_dir / "valid_datas_openai_format.jsonl"
    training_config_path = paths.config_dir / "training_config.yaml"
    inference_config_path = paths.config_dir / "inference_config.yaml"
    
    # 获取集群列表
    cluster_list = list(cluster_injection_sqls(read_json_file(test_sqls_path)).keys())
    
    # 初始化组件
    attacker = Attacker(
        number_of_training_sqls=NUM_TRAINING_SQLS,
        cluster_list=cluster_list,
        normal_sqls_path=str(normal_sqls_path),
        raw_datas_dir=str(paths.raw_datas_dir),
    )
    
    cot_producer = CoT_producer(schemas_file=str(paths.raw_datas_dir / "schema.json"))
    
    defender = Defender(
        valid_file=str(valid_datas_path),
        training_config_path=str(training_config_path),
        inference_config_path=str(inference_config_path),
    )
    
    verifier = Verifier(cluster_list=cluster_list)
    
    return attacker, cot_producer, defender, verifier


def run_training_round(
    round_idx: int,
    paths: ProjectPaths,
    attacker: Attacker,
    cot_producer: CoT_producer,
    defender: Defender,
    verifier: Verifier,
    strategy: str = None,
) -> None:
    """执行单轮训练循环
    
    Args:
        round_idx: 当前轮次索引
        paths: 项目路径配置
        attacker: 攻击者组件
        cot_producer: CoT 数据生成器
        defender: 防御者组件
        verifier: 验证器组件
        strategy: 采样策略，如果为 None 则根据轮次自动选择
    """
    print(f"\n{'=' * 50}")
    print(f"Round {round_idx}")
    print(f"{'=' * 50}")
    
    # 根据轮次自动选择策略
    if strategy is None:
        if round_idx < PROBABILITY_ROUNDS:
            strategy = ATTACKER_STRATEGY
            print(f"📊 使用策略: {strategy} (概率采样)")
        else:
            strategy = ATTACKER_STRATEGY_TOP_K
            print(f"🎯 使用策略: {strategy} (Top-K 采样，聚焦高权重集群)")
    
    # 确定当前模型路径
    if round_idx == 0:
        current_model_path = paths.base_model_path
    else:
        current_model_path = paths.temp_datas_dir / f"round_{round_idx-1}" / "merged_model"
    
    # 创建输出目录
    round_output_dir = paths.temp_datas_dir / f"round_{round_idx}"
    round_output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. 生成训练 SQL
    train_sqls, clusters_probability_distribution = attacker.generate_training_sqls(
        gamma=ATTACKER_GAMMA,
        clusters_weight_distribution=verifier.get_weights(),
        strategy=strategy,
        k=ATTACKER_K,
    )
    
    # 2. 转换为训练数据格式
    training_datas = cot_producer.run(training_sqls=train_sqls)
    train_datas_path = round_output_dir / "train_datas.jsonl"
    write_jsonl_file(str(train_datas_path), training_datas)
    
    # 3. 训练和评估模型
    results = defender.run_all(
        base_model=str(current_model_path),
        train_file=str(train_datas_path),
        output_root=str(round_output_dir),
        do_inference=True,
    )
    
    # 4. 更新验证器权重
    verifier.update_reward(results=results)
    verifier.update_weight(
        gamma=VERIFIER_GAMMA,
        cluster_probability_distribution=clusters_probability_distribution,
    )
    
    # 5. 保存集群权重
    current_weights = verifier.get_weights()
    weights_data = [
        {"cluster": key, "weight": weight}
        for key, weight in current_weights.items()
    ]
    write_jsonl_file(
        str(round_output_dir / "cluster_weights.jsonl"),
        weights_data,
    )
    
    # 6. 清理上一轮的模型（节省空间）
    if round_idx > 0:
        prev_model_dir = paths.temp_datas_dir / f"round_{round_idx-1}" / "merged_model"
        delete_folder_if_exists(str(prev_model_dir))


def run_training_loop(start_round: int = 0, breakpoint_round: int = -1) -> None:
    """执行完整的训练循环"""
    paths = ProjectPaths.create()
    os.chdir(paths.project_root)
    
    # 初始化组件
    attacker, cot_producer, defender, verifier = initialize_components(paths)
    
    # 如果从断点恢复，加载权重
    if breakpoint_round >= 0:
        weights_file = paths.temp_datas_dir / f"round_{breakpoint_round}" / "cluster_weights.jsonl"
        if weights_file.exists():
            current_weights = read_jsonl_file(str(weights_file))
            verifier.set_weights({
                item["cluster"]: item["weight"]
                for item in current_weights
            })
            print(f"✓ 从 round {breakpoint_round} 恢复权重")
        else:
            print(f"⚠ 警告: 未找到断点权重文件 {weights_file}")
    
    # 执行训练循环
    for round_idx in range(start_round, NUM_ROUNDS):
        if breakpoint_round >= 0 and round_idx <= breakpoint_round:
            continue
        
        # 根据轮次自动选择策略（前 PROBABILITY_ROUNDS 轮用概率采样，之后用 top-k）
        run_training_round(
            round_idx=round_idx,
            paths=paths,
            attacker=attacker,
            cot_producer=cot_producer,
            defender=defender,
            verifier=verifier,
            strategy=None,  # None 表示自动选择
        )


# ==================== 主函数 ====================
def main() -> None:
    """主入口函数"""
    # run_training_loop(start_round=0)
    run_training_loop(start_round=0, breakpoint_round=3)  # 从断点恢复


if __name__ == "__main__":
    main()