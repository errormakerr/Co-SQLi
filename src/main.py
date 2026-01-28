from Attacker.Attacker import Attacker
from CoT_producer.CoT_producer import CoT_producer
from Defender.defender import Defender
from Verifier.verifier import Verifier

from utils.cluster import cluster_injection_sqls
from utils.json_operation import read_json_file, write_jsonl_file, read_jsonl_file
import os
from pathlib import Path
<<<<<<< HEAD
=======
import shutil
>>>>>>> d702884 (stable version)

def delete_folder_if_exists(folder_path):
    """
    检查文件夹是否存在，如果存在则删除该文件夹及其所有内容。
    """
    # 1. 检查路径是否存在
    if os.path.exists(folder_path):
        # 2. 检查是否确实是一个目录（防止误删同名文件）
        if os.path.isdir(folder_path):
            try:
                # 3. 递归删除目录及内容
                shutil.rmtree(folder_path)
                print(f"成功删除文件夹: {folder_path}")
            except OSError as e:
                print(f"删除失败: {e.strerror}")
            except Exception as e:
                print(f"发生未知错误: {e}")
        else:
            print(f"错误: '{folder_path}' 存在，但它是一个文件，不是文件夹。")
    else:
        print(f"文件夹不存在，跳过: {folder_path}")

# def main():
#     PROJECT_ROOT = Path(__file__).resolve().parents[1]   # .../SQLI
#     os.chdir(PROJECT_ROOT)
    
#     RAW_DATAS_DIR = PROJECT_ROOT / "data" / "raw_datas_for_generation"
#     BENCHMARK_DIR = PROJECT_ROOT / "data" / "benchmark"
#     TEMP_DATAS_DIR = r"/home/panhao/model/temp_data/Qwen2.5-Coder-3B-Instruct_without_modify"
#     CONFIG_DIR = PROJECT_ROOT / "config"
#     BASE_MODEL_PATH = Path("/home/panhao/model/base_model/Qwen2.5-Coder-3B-Instruct")
    
#     normal_sqls_path = RAW_DATAS_DIR/"normal_sqls.json"
    
#     test_sqls_path = BENCHMARK_DIR/"test_sqls.json"
#     train_sqls_path = BENCHMARK_DIR/"train_sqls.json"
#     valid_sqls_path = BENCHMARK_DIR/"valid_sqls.json"
    
#     test_datas_path = BENCHMARK_DIR/"test_datas_openai_format.jsonl"
#     train_datas_path = BENCHMARK_DIR/"train_datas_openai_format.jsonl"
#     valid_datas_path = BENCHMARK_DIR/"valid_datas_openai_format.jsonl"
    
#     training_config_path = CONFIG_DIR/"training_config.yaml"
#     inference_config_path = CONFIG_DIR/"inference_config.yaml"
#     cluster_list = cluster_injection_sqls(read_json_file(test_sqls_path)).keys()
    
#     attacker = Attacker(number_of_training_sqls=60, cluster_list=cluster_list, normal_sqls_path=normal_sqls_path, raw_datas_dir=RAW_DATAS_DIR,)
#     cot_producer = CoT_producer(schemas_file=f"{RAW_DATAS_DIR}/schema.json")
#     defender = Defender(valid_file=valid_datas_path, training_config_path=training_config_path, inference_config_path=inference_config_path,)
#     verifier = Verifier(cluster_list=cluster_list,)
    
#     # 进行十轮攻击-防御-验证循环
#     for round_idx in range(40):
#         print(f"================= Round {round_idx} =================")
#         current_model_path = BASE_MODEL_PATH if round_idx == 0 else f"{TEMP_DATAS_DIR}/round_{round_idx-1}/merged_model"
#         os.makedirs(f"{TEMP_DATAS_DIR}/round_{round_idx}", exist_ok=True)
#         train_sqls, clusters_probability_distribution = attacker.generate_training_sqls(gamma=0.5, clusters_weight_distribution=verifier.get_weights(), strategy="by_probability", k=5)
#         training_datas = cot_producer.run(training_sqls=train_sqls)
#         write_jsonl_file(f"{TEMP_DATAS_DIR}/round_{round_idx}/train_datas.jsonl", training_datas)
#         results = defender.run_all(base_model=current_model_path, train_file=f"{TEMP_DATAS_DIR}/round_{round_idx}/train_datas.jsonl", output_root=f"{TEMP_DATAS_DIR}/round_{round_idx}", do_inference=True,)
#         verifier.update_reward(results=results)
#         verifier.update_weight(gamma=0.5, cluster_probability_distribution=clusters_probability_distribution)
#         current_weights = verifier.get_weights()
#         write_jsonl_file(f"{TEMP_DATAS_DIR}/round_{round_idx}/cluster_weights.jsonl", [{"cluster": key, "weight": weight} for key, weight in current_weights.items()])
#         # 删除上一个回合的模型，节省空间
#         delete_folder_if_exists(f"{TEMP_DATAS_DIR}/round_{round_idx-1}/merged_model")
        
def main():
    PROJECT_ROOT = Path(__file__).resolve().parents[1]   # .../SQLI
    os.chdir(PROJECT_ROOT)
    
    RAW_DATAS_DIR = PROJECT_ROOT / "data" / "raw_datas_for_generation"
    BENCHMARK_DIR = PROJECT_ROOT / "data" / "benchmark"
<<<<<<< HEAD
    TEMP_DATAS_DIR = PROJECT_ROOT / "data" / "temp_data"
    CONFIG_DIR = PROJECT_ROOT / "config"
    BASE_MODEL_PATH = Path("/home/linxiaotian/llamafactory/LLaMA-Factory/model/Qwen/Qwen2.5-Coder-3B-Instruct")
    
    normal_sqls_path = RAW_DATAS_DIR/"normal_sqls.json"
    
    test_sqls_path = BENCHMARK_DIR/"test_sqls.json"
    train_sqls_path = BENCHMARK_DIR/"train_sqls.json"
    valid_sqls_path = BENCHMARK_DIR/"valid_sqls.json"
    
    test_datas_path = BENCHMARK_DIR/"test_datas_openai_format.jsonl"
    train_datas_path = BENCHMARK_DIR/"train_datas_openai_format.jsonl"
    valid_datas_path = BENCHMARK_DIR/"valid_datas_openai_format.jsonl"
    
    training_config_path = CONFIG_DIR/"training_config.yaml"
    inference_config_path = CONFIG_DIR/"inference_config.yaml"
    cluster_list = cluster_injection_sqls(read_json_file(test_sqls_path)).keys()
=======
    TEMP_DATAS_DIR = r"/home/panhao/model/temp_data/Qwen2.5-Coder-3B-Instruct_without_modify"
    CONFIG_DIR = PROJECT_ROOT / "config"
    BASE_MODEL_PATH = Path("/home/panhao/model/base_model/Qwen2.5-Coder-3B-Instruct")
>>>>>>> d702884 (stable version)
    
    normal_sqls_path = RAW_DATAS_DIR/"normal_sqls.json"
    
    test_sqls_path = BENCHMARK_DIR/"test_sqls.json"
    train_sqls_path = BENCHMARK_DIR/"train_sqls.json"
    valid_sqls_path = BENCHMARK_DIR/"valid_sqls.json"
    
    test_datas_path = BENCHMARK_DIR/"test_datas_openai_format.jsonl"
    train_datas_path = BENCHMARK_DIR/"train_datas_openai_format.jsonl"
    valid_datas_path = BENCHMARK_DIR/"valid_datas_openai_format.jsonl"
    
    training_config_path = CONFIG_DIR/"training_config.yaml"
    inference_config_path = CONFIG_DIR/"inference_config.yaml"
    cluster_list = cluster_injection_sqls(read_json_file(test_sqls_path)).keys()
    
    attacker = Attacker(number_of_training_sqls=60, cluster_list=cluster_list, normal_sqls_path=normal_sqls_path, raw_datas_dir=RAW_DATAS_DIR,)
    cot_producer = CoT_producer(schemas_file=f"{RAW_DATAS_DIR}/schema.json")
    defender = Defender(valid_file=valid_datas_path, training_config_path=training_config_path, inference_config_path=inference_config_path,)
    verifier = Verifier(cluster_list=cluster_list,)
    current_weights = read_jsonl_file(r"/home/panhao/model/temp_data/Qwen2.5-Coder-3B-Instruct_without_modify/round_17/cluster_weights.jsonl")
    verifier.set_weights({item["cluster"]: item["weight"] for item in current_weights})
    
    # 进行十轮攻击-防御-验证循环
    for round_idx in range(40):
        if round_idx < 18:
            continue
        
        print(f"================= Round {round_idx} =================")
        current_model_path = BASE_MODEL_PATH if round_idx == 0 else f"{TEMP_DATAS_DIR}/round_{round_idx-1}/merged_model"
        os.makedirs(f"{TEMP_DATAS_DIR}/round_{round_idx}", exist_ok=True)
<<<<<<< HEAD
        
        train_sqls, clusters_probability_distribution = attacker.generate_training_sqls(gamma=0.5, clusters_weight_distribution=verifier.get_weights(), strategy="by_probability", k=10)
=======
        train_sqls, clusters_probability_distribution = attacker.generate_training_sqls(gamma=0.5, clusters_weight_distribution=verifier.get_weights(), strategy="by_probability", k=5)
>>>>>>> d702884 (stable version)
        training_datas = cot_producer.run(training_sqls=train_sqls)
        write_jsonl_file(f"{TEMP_DATAS_DIR}/round_{round_idx}/train_datas.jsonl", training_datas)
        results = defender.run_all(base_model=current_model_path, train_file=f"{TEMP_DATAS_DIR}/round_{round_idx}/train_datas.jsonl", output_root=f"{TEMP_DATAS_DIR}/round_{round_idx}", do_inference=True,)
        verifier.update_reward(results=results)
        verifier.update_weight(gamma=0.5, cluster_probability_distribution=clusters_probability_distribution)
        current_weights = verifier.get_weights()
        write_jsonl_file(f"{TEMP_DATAS_DIR}/round_{round_idx}/cluster_weights.jsonl", [{"cluster": key, "weight": weight} for key, weight in current_weights.items()])
        # 删除上一个回合的模型，节省空间
        delete_folder_if_exists(f"{TEMP_DATAS_DIR}/round_{round_idx-1}/merged_model")
        
if __name__ == "__main__":
    main()