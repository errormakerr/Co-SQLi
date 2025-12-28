import json

def read_json_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            data = json.load(file)
            return data
    except FileNotFoundError:
        print(f"错误：找不到文件 {file_path}")
        return None
    except json.JSONDecodeError as e:
        print(f"错误：JSON格式不正确 - {e}")
        return None
    except Exception as e:
        print(f"读取文件时发生错误：{e}")
        return None

def write_json_file(file_path, data):
    try:
        with open(file_path, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
            print(f"数据已成功写入 {file_path}")
    except Exception as e:
        print(f"写入文件时发生错误：{e}")
        
def read_jsonl_file(file_path):
    data = []
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            for line_num, line in enumerate(file, 1):
                line = line.strip()
                if line:  # 跳过空行
                    try:
                        json_obj = json.loads(line)
                        data.append(json_obj)
                    except json.JSONDecodeError as e:
                        print(f"警告：第{line_num}行JSON格式错误 - {e}")
                        continue
        print(f"成功读取 {len(data)} 条记录从 {file_path}")
        return data
    except FileNotFoundError:
        print(f"错误：找不到文件 {file_path}")
        return []
    except Exception as e:
        print(f"读取文件时发生错误：{e}")
        return []
    
def write_jsonl_file(file_path, data) -> bool:
    try:
        
        with open(file_path, 'w', encoding='utf-8') as file:
            if isinstance(data, dict):
                # 单个字典
                file.write(json.dumps(data, ensure_ascii=False) + '\n')
                count = 1
            elif isinstance(data, list):
                # 字典列表
                for item in data:
                    if isinstance(item, dict):
                        file.write(json.dumps(item, ensure_ascii=False) + '\n')
                    else:
                        print(f"警告：跳过非字典项目 {item}")
                count = len([item for item in data if isinstance(item, dict)])
            else:
                raise ValueError("数据必须是字典或字典列表")
        
        print(f"成功写入 {count} 条记录到 {file_path}")
        return True
    except Exception as e:
        print(f"写入文件时发生错误：{e}")
        return False

