#!/bin/bash

# SQL注入检测模型推理脚本

# 设置路径
MODEL_PATH="/hpc2hdd/home/xlin420/DCAI/Unids/model_results/qwen2.5-coder-3b-sft-1130/lora_merged_qwen2.5-coder-3b-sft-1130/"
TEST_FILE="/hpc2hdd/home/xlin420/AdversarialFrame/data/train_data1130/test_sqls_sft1130_2.jsonl"
OUTPUT_FILE="/hpc2hdd/home/xlin420/AdversarialFrame/results/inference_results_qwen_3b_coder_instruct_data_1130_2.jsonl"

# 超参数设置
BATCH_SIZE=4
MAX_NEW_TOKENS=128
MAX_SEQ_LENGTH=2048
TEMPERATURE=0.1  # 低温度使输出更确定
TOP_P=0.9

# 可选：限制测试样本数量（用于快速测试，注释掉则使用全部数据）
# MAX_SAMPLES=100

echo "=================================================="
echo "SQL注入检测模型推理"
echo "=================================================="
echo "模型: $MODEL_PATH"
echo "测试数据: $TEST_FILE"
echo "输出文件: $OUTPUT_FILE"
echo "=================================================="

# 构建命令
CMD="python /hpc2hdd/home/xlin420/AdversarialFrame/src/inference_and_eval.py \
    --model_path $MODEL_PATH \
    --test_file $TEST_FILE \
    --output_file $OUTPUT_FILE \
    --batch_size $BATCH_SIZE \
    --max_new_tokens $MAX_NEW_TOKENS \
    --max_seq_length $MAX_SEQ_LENGTH \
    --temperature $TEMPERATURE \
    --top_p $TOP_P"

# 如果设置了MAX_SAMPLES，添加到命令中
if [ ! -z "$MAX_SAMPLES" ]; then
    CMD="$CMD --max_samples $MAX_SAMPLES"
fi

# 如果模型需要trust_remote_code，添加该参数
# CMD="$CMD --trust_remote_code"

# 运行推理
eval $CMD

echo ""
echo "=================================================="
echo "✅ 推理完成！"
echo "=================================================="
echo "结果文件: $OUTPUT_FILE"
echo "统计文件: ${OUTPUT_FILE%.jsonl}_stats.json"
echo "=================================================="

