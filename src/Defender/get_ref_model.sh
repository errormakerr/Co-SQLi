# Set environment variables
export CUDA_VISIBLE_DEVICES=0,1
NUM_GPUS=2

## path
# cluster_root_path=YOUR_ROOT_PATH
# root_data_path="raw_data"

# base model
base_model="/hpc2hdd/home/xlin420/DCAI/hf_models/Qwen2-7B" #"meta-llama/Llama-3.1-8B" "mistralai/Mistral-7B-v0.3"
token_select_pattern=default 
random_seed=42
data_prop=0.6
BATCH_SIZE_PER_GPU=2
# model_path=$cluster_root_path/$(basename "$base_model")/data_prop_${data_prop}

# train_data_tag="ds2-10k-warmup"
# train_data="${root_data_path}/${train_data_tag}.json"

# save path
model_path="/hpc2hdd/home/xlin420/DCAI/Unids/model_results/tulu3-qwen-select_llama3-test-top50k-1121"

# training data path
train_data="/hpc2hdd/home/xlin420/DCAI/Unids/data/pool_messages_selectIT_top5w.jsonl"
# finetune
bash_src/finetune.sh "$base_model" "$train_data" "$BATCH_SIZE_PER_GPU" "$NUM_GPUS" "$model_path" "$data_prop" "$token_select_pattern" "$random_seed"






