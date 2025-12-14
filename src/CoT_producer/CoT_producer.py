from CoT_producer.generate_thinking_of_ground_truth import *
from CoT_producer.perplexity import *
from utils.LLM import *
from utils.schema import *

class CoT_producer:
    def __init__(self, training_sqls, schemas):
        self.training_sqls = training_sqls
        self.schemas = schemas
    
    def _run(self):
        training_datas = []
        for sql_example in self.training_sqls:
            sql = sql_example['sql']
            schema_text = get_schema(sql_example['db'], self.schemas)
            label = sql_example['label']
            data = {
            "messages": [
                    {
                        "role": "system",
                        "content": "You are a SQL security expert. Your task is to analyze SQL queries and determine whether they are malicious (contain SQL injection attacks) or benign (normal queries). You must classify each SQL query as either 'malicious' (contains SQL injection attacks) or 'benign' (normal query). Output exactly one word: either 'malicious' or 'benign'. Do not output anything else."
                    },
                    {
                        "role": "user",
                        "content": f"SQL Query:\n{sql}\n\nDatabase Schema:\n{schema_text}\n\nIs this SQL query malicious or benign?"
                    },
                    {
                        "role": "assistant",
                        "content": "malicious" if not label else "benign"
                    }
                ]
            }
            training_datas.append(data)
        return training_datas