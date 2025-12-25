from Attacker.Attacker import Attacker
from CoT_producer.CoT_producer import CoT_producer
from Defender.defender import Defender
from Verifier.verifier import Verifier

from utils.cluster import cluster_injection_sqls
from utils.json_operation import read_json_file, write_jsonl_file
import os


def main():
    attacker = Attacker()
    RAW_DATAS_DIR = r"data\raw_datas_for_generation"
    BENCHMARK_DIR = r"data\benchmark"
    TEMP_DATAS_DIR = r"data\temp_data"
    CONFIG_DIR = r"data\config"
    BASE_MODEL_PATH = ""
    
    normal_sqls_path = f"{RAW_DATAS_DIR}/normal_sqls.json"
    test_sqls = f"{BENCHMARK_DIR}/test_sqls.json"
    train_sqls = f"{BENCHMARK_DIR}/train_sqls.json"
    valid_sqls = f"{BENCHMARK_DIR}/valid_sqls.json"
    training_config_path = F"{CONFIG_DIR}/training_config.yaml"
    inference_config_path = f"{CONFIG_DIR}/inference_config.yaml"
    cluster_list = cluster_injection_sqls(read_json_file(test_sqls)).keys()
    
    attacker = Attacker(number_of_training_sqls=50, cluster_list=cluster_list, normal_sqls_path=normal_sqls_path, raw_datas_dir=RAW_DATAS_DIR,)
    cot_producer = CoT_producer(schemas_file=f"{RAW_DATAS_DIR}/schema.json")
    defender = Defender(valid_file=valid_sqls, training_config_path=training_config_path, inference_config_path=inference_config_path,)
    verifier = Verifier(cluster_list=cluster_list,)
    
    # 进行十轮攻击-防御-验证循环
    for round_idx in range(10):
        current_model_path = BASE_MODEL_PATH if round_idx == 0 else f"{TEMP_DATAS_DIR}/round_{round_idx-1}/merged_model"
        os.makedirs(f"{TEMP_DATAS_DIR}/round_{round_idx}", exist_ok=True)
        
        train_sqls, clusters_probability_distribution = attacker.generate_training_sqls(gamma=0.5, clusters_weight_distribution=verifier.get_weights(),)
        training_datas = cot_producer.run(training_sqls=train_sqls)
        write_jsonl_file(f"{TEMP_DATAS_DIR}/round_{round_idx}/train_datas.jsonl", training_datas)
        results = defender.run_all(base_model=current_model_path, train_file=f"{TEMP_DATAS_DIR}/round_{round_idx}/train_datas.jsonl", output_root=f"{TEMP_DATAS_DIR}/round_{round_idx}", do_inference=True,)
        verifier.update_reward(results=results)
        verifier.update_weight(gamma=0.5, cluster_probability_distribution=clusters_probability_distribution)
        
if __name__ == "__main__":
    main()
    
    
    






