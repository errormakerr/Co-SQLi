# from CoT_producer.generate_thinking_of_ground_truth import *
# from CoT_producer.perplexity import *
# from utils.LLM import *
from .schema_reprecess import process_data, load_schemas
from utils.json_operation import read_json_file

class CoT_producer:
    def __init__(self, schemas_file):
        self.schemas = load_schemas(schemas_file)
    
    def run(self, training_sqls):
        # 处理数据，生成 CoT 格式数据
        training_data = process_data(
            sql_data=training_sqls,
            schemas=self.schemas,
            format_type="openai",
        )
        return training_data
    
def main():
    schemas_file = r"data\raw_datas_for_generation\schema.json"
    cot_producer = CoT_producer(schemas_file=schemas_file)
    
    # 示例输入 SQL 列表
    training_sqls = read_json_file(r"data\temp_data\train_sqls.json")[:10]
    
    training_datas = cot_producer.run(training_sqls=training_sqls)
    for item in training_datas:
        print(item, "\n")
        
if __name__ == "__main__":
    main()