#!/usr/bin/env python
# coding=utf-8
"""
模型推理和准确率评估脚本
用于加载微调后的模型，对测试数据集进行推理，并计算准确率
"""

import argparse
import json
import os
import torch
from tqdm import tqdm
from transformers import AutoTokenizer, AutoModelForCausalLM
from typing import List, Dict
import re
from sklearn.metrics import precision_score, recall_score, f1_score, classification_report


def parse_args():
    parser = argparse.ArgumentParser(description="模型推理和准确率评估")
    parser.add_argument(
        "--model_path",
        type=str,
        default="/hpc2hdd/home/xlin420/DCAI/hf_models/Qwen2.5-Coder-7B-Instruct",
        help="模型路径"
    )
    parser.add_argument(
        "--test_file",
        type=str,
        default="/hpc2hdd/home/xlin420/AdversarialFrame/data/sft_test_data.jsonl",
        help="测试数据文件路径"
    )
    parser.add_argument(
        "--output_file",
        type=str,
        default="/hpc2hdd/home/xlin420/AdversarialFrame/results/inference_results_base.jsonl",
        help="推理结果输出文件路径"
    )
    parser.add_argument(
        "--batch_size",
        type=int,
        default=1,
        help="批次大小"
    )
    parser.add_argument(
        "--max_new_tokens",
        type=int,
        default=128,
        help="生成的最大token数"
    )
    parser.add_argument(
        "--max_seq_length",
        type=int,
        default=2048,
        help="最大序列长度"
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.1,
        help="生成温度，越低越确定性"
    )
    parser.add_argument(
        "--top_p",
        type=float,
        default=0.9,
        help="Top-p采样参数"
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cuda" if torch.cuda.is_available() else "cpu",
        help="运行设备"
    )
    parser.add_argument(
        "--trust_remote_code",
        action="store_true",
        help="是否信任远程代码"
    )
    parser.add_argument(
        "--max_samples",
        type=int,
        default=None,
        help="最大测试样本数（用于调试）"
    )
    
    return parser.parse_args()


def load_test_data(file_path: str, max_samples: int = None) -> List[Dict]:
    """加载测试数据"""
    print(f"📖 加载测试数据: {file_path}")
    data = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for idx, line in enumerate(f):
            if max_samples and idx >= max_samples:
                break
            data.append(json.loads(line.strip()))
    print(f"✅ 加载了 {len(data)} 条测试数据")
    return data


def build_prompt_from_messages(messages: List[Dict]) -> str:
    """
    根据messages格式构建prompt
    与finetune.py中的encode_with_messages_format保持一致
    """
    prompt_text = ""
    for message in messages:
        if message["role"] == "system":
            prompt_text += "<|system|>\n" + message["content"].strip() + "\n"
        elif message["role"] == "user":
            prompt_text += "<|user|>\n" + message["content"].strip() + "\n"
        elif message["role"] == "assistant":
            # 推理时，我们只构建到assistant之前的部分
            prompt_text += "<|assistant|>\n"
            break
    return prompt_text.strip()


def extract_answer(text: str) -> str:
    """
    从生成的文本中提取答案
    支持两种格式：
    1. <answer>...</answer> 标签格式
    2. 直接包含 "benign" 或 "malicious" 的文本
    """
    text = text.strip()
    
    # 首先尝试从 <answer> 标签中提取
    answer_pattern = r'<answer>\s*(.*?)\s*</answer>'
    match = re.search(answer_pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        answer_content = match.group(1).strip()
        # 从提取的内容中判断是 benign 还是 malicious
        answer_lower = answer_content.lower()
        if "malicious" in answer_lower:
            # 检查是否在说"不是malicious"之类的
            if "not malicious" in answer_lower or "is benign" in answer_lower:
                return "benign"
            return "malicious"
        elif "benign" in answer_lower:
            return "benign"
        else:
            # 如果标签内没有明确的关键词，返回标签内容
            return answer_content
    
    # 如果没有找到 <answer> 标签，使用原来的逻辑
    text_lower = text.lower()
    if "malicious" in text_lower:
        # 检查是否在说"不是malicious"之类的
        if "not malicious" in text_lower or "is benign" in text_lower:
            return "benign"
        return "malicious"
    elif "benign" in text_lower:
        return "benign"
    else:
        # 如果都没有，返回原文的第一个单词
        words = text.split()
        if words:
            return words[0]
        return text


def get_ground_truth(messages: List[Dict]) -> str:
    """从messages中提取真实答案"""
    for message in messages:
        if message["role"] == "assistant":
            return message["content"].strip().lower()
    return ""


def calculate_metrics(y_true: List[str], y_pred: List[str]) -> Dict[str, float]:
    """
    计算二分类指标：precision, recall, f1
    专门针对 benign vs malicious 二分类任务
    """
    # 将标签转换为二进制格式：malicious=1, benign=0
    def label_to_binary(label):
        return 1 if label.lower() == 'malicious' else 0
    
    y_true_binary = [label_to_binary(label) for label in y_true]
    y_pred_binary = [label_to_binary(label) for label in y_pred]
    
    # 计算二分类指标
    precision = precision_score(y_true_binary, y_pred_binary, zero_division=0)
    recall = recall_score(y_true_binary, y_pred_binary, zero_division=0)
    f1 = f1_score(y_true_binary, y_pred_binary, zero_division=0)
    
    # 计算每个类别的指标（二分类）
    precision_per_class = precision_score(y_true_binary, y_pred_binary, average=None, zero_division=0)
    recall_per_class = recall_score(y_true_binary, y_pred_binary, average=None, zero_division=0)
    f1_per_class = f1_score(y_true_binary, y_pred_binary, average=None, zero_division=0)
    
    # 构建每个类别的详细指标
    per_class_metrics = {
        'benign': {
            'precision': float(precision_per_class[0]) if len(precision_per_class) > 0 else 0.0,
            'recall': float(recall_per_class[0]) if len(recall_per_class) > 0 else 0.0,
            'f1': float(f1_per_class[0]) if len(f1_per_class) > 0 else 0.0
        },
        'malicious': {
            'precision': float(precision_per_class[1]) if len(precision_per_class) > 1 else 0.0,
            'recall': float(recall_per_class[1]) if len(recall_per_class) > 1 else 0.0,
            'f1': float(f1_per_class[1]) if len(f1_per_class) > 1 else 0.0
        }
    }
    
    return {
        'precision': float(precision),
        'recall': float(recall),
        'f1': float(f1),
        'per_class_metrics': per_class_metrics,
        'labels': ['benign', 'malicious']
    }


def run_inference(args):
    """执行推理"""
    print("="*80)
    print("🚀 开始模型推理和评估")
    print("="*80)
    
    # 1. 加载模型和tokenizer
    print(f"\n📦 加载模型: {args.model_path}")
    tokenizer = AutoTokenizer.from_pretrained(
        args.model_path,
        trust_remote_code=args.trust_remote_code,
        padding_side='left'  # 对于生成任务使用左填充
    )
    
    # 确保有pad_token
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    
    model = AutoModelForCausalLM.from_pretrained(
        args.model_path,
        trust_remote_code=args.trust_remote_code,
        torch_dtype=torch.float16 if args.device == "cuda" else torch.float32,
        device_map="auto" if args.device == "cuda" else None
    )
    
    if args.device == "cpu":
        model = model.to(args.device)
    
    model.eval()
    print("✅ 模型加载完成")
    
    # 2. 加载测试数据
    test_data = load_test_data(args.test_file, args.max_samples)
    
    # 3. 推理
    results = []
    correct = 0
    total = 0
    
    print(f"\n🔄 开始推理 (批次大小={args.batch_size})...")
    
    # 创建输出目录
    os.makedirs(os.path.dirname(args.output_file), exist_ok=True)
    
    with torch.no_grad():
        for i in tqdm(range(0, len(test_data), args.batch_size)):
            batch_data = test_data[i:i+args.batch_size]
            
            # 构建prompts
            prompts = []
            ground_truths = []
            for example in batch_data:
                messages = example['messages']
                prompt = build_prompt_from_messages(messages)
                ground_truth = get_ground_truth(messages)
                
                prompts.append(prompt)
                ground_truths.append(ground_truth)
            
            # Tokenize
            inputs = tokenizer(
                prompts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=args.max_seq_length
            ).to(model.device)
            
            # 生成
            outputs = model.generate(
                **inputs,
                max_new_tokens=args.max_new_tokens,
                temperature=args.temperature,
                top_p=args.top_p,
                do_sample=True if args.temperature > 0 else False,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
            
            # 解码
            for j, output in enumerate(outputs):
                # 只取生成的部分（去掉输入的prompt）
                input_length = inputs['input_ids'][j].shape[0]
                generated_tokens = output[input_length:]
                generated_text = tokenizer.decode(generated_tokens, skip_special_tokens=True)
                
                # 提取答案
                predicted_answer = extract_answer(generated_text)
                ground_truth = ground_truths[j]
                
                # 判断是否正确
                is_correct = predicted_answer == ground_truth
                if is_correct:
                    correct += 1
                total += 1
                
                # 保存结果
                result = {
                    "id": i + j,
                    "prompt": prompts[j],
                    "generated_text": generated_text,
                    "predicted_answer": predicted_answer,
                    "ground_truth": ground_truth,
                    "is_correct": is_correct
                }
                results.append(result)
    
    # 4. 计算准确率和分类指标
    accuracy = correct / total if total > 0 else 0
    
    # 提取真实标签和预测标签用于计算分类指标
    y_true = [result["ground_truth"] for result in results]
    y_pred = [result["predicted_answer"] for result in results]
    
    # 计算分类指标
    metrics = calculate_metrics(y_true, y_pred)
    
    print("\n" + "="*80)
    print("📊 评估结果")
    print("="*80)
    print(f"总样本数: {total}")
    print(f"正确数量: {correct}")
    print(f"准确率: {accuracy:.4f} ({accuracy*100:.2f}%)")
    print()
    print("📈 二分类指标:")
    print(f"  Precision: {metrics['precision']:.4f}")
    print(f"  Recall: {metrics['recall']:.4f}")
    print(f"  F1: {metrics['f1']:.4f}")
    print()
    print("📊 各类别详细指标:")
    for label, class_metrics in metrics['per_class_metrics'].items():
        print(f"  {label}:")
        print(f"    Precision: {class_metrics['precision']:.4f}")
        print(f"    Recall: {class_metrics['recall']:.4f}")
        print(f"    F1: {class_metrics['f1']:.4f}")
    print("="*80)
    
    # 5. 保存结果
    print(f"\n💾 保存推理结果到: {args.output_file}")
    with open(args.output_file, 'w', encoding='utf-8') as f:
        for result in results:
            f.write(json.dumps(result, ensure_ascii=False) + '\n')
    
    # 保存统计信息
    stats_file = args.output_file.replace('.jsonl', '_stats.json')
    stats = {
        "total_samples": total,
        "correct": correct,
        "incorrect": total - correct,
        "accuracy": accuracy,
        "classification_metrics": {
            "precision": metrics['precision'],
            "recall": metrics['recall'],
            "f1": metrics['f1'],
            "per_class_metrics": metrics['per_class_metrics'],
            "labels": metrics['labels']
        },
        "model_path": args.model_path,
        "test_file": args.test_file,
        "hyperparameters": {
            "max_new_tokens": args.max_new_tokens,
            "temperature": args.temperature,
            "top_p": args.top_p,
            "batch_size": args.batch_size
        }
    }
    
    with open(stats_file, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    
    print(f"💾 保存统计信息到: {stats_file}")
    print("\n✅ 完成!")
    
    return accuracy, results


def main():
    args = parse_args()
    
    # 打印配置
    print("\n⚙️  配置信息:")
    print(f"  - 模型路径: {args.model_path}")
    print(f"  - 测试文件: {args.test_file}")
    print(f"  - 输出文件: {args.output_file}")
    print(f"  - 设备: {args.device}")
    print(f"  - 批次大小: {args.batch_size}")
    print(f"  - 最大新生成tokens: {args.max_new_tokens}")
    print(f"  - 温度: {args.temperature}")
    print(f"  - Top-p: {args.top_p}")
    if args.max_samples:
        print(f"  - 最大样本数: {args.max_samples}")
    print()
    
    # 运行推理
    accuracy, results = run_inference(args)
    
    return accuracy


if __name__ == "__main__":
    main()

