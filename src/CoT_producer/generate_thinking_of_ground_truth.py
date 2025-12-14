from utils.json_operation import *
from utils.yaml_operation import *
from utils.schema import *
from utils.j2_opeartion import *

prompt_template_dir = "prompt_templates/CoT_producer"

long_COT_prompt_template_for_normal_sql = load_prompt_template(prompt_template_dir, "generate_long_thinking_for_normal_sql.j2")
long_COT_prompt_template_for_injection_sql = load_prompt_template(prompt_template_dir, "generate_long_thinking_for_injection_sql.j2")
short_COT_prompt_template_for_normal_sql = load_prompt_template(prompt_template_dir, "generate_short_thinking_for_normal_sql.j2")
short_COT_prompt_template_for_injection_sql = load_prompt_template(prompt_template_dir, "generate_short_thinking_for_injection_sql.j2")

background_for_Error_based_Attack = load_prompt_template(prompt_template_dir, "background_for_Error_based_Attack.j2")
background_for_Union_query_Attack = load_prompt_template(prompt_template_dir, "background_for_Union_query_Attack.j2")
background_for_Tautologies_Attack = load_prompt_template(prompt_template_dir, "background_for_Tautologies_Attack.j2")
background_for_Piggy_backed_Queries_Attack = load_prompt_template(prompt_template_dir, "background_for_Piggy_backed_Queries_Attack.j2")
background_for_Boolean_based_Inference_Attack = load_prompt_template(prompt_template_dir, "background_for_Boolean_based_Inference_Attack.j2")
background_for_Time_based_Inference_Attack = load_prompt_template(prompt_template_dir, "background_for_Time_based_Inference_Attack.j2")
advance_payload_anlysis_guiduance = load_prompt_template(prompt_template_dir, "advance_payload_anlysis_guiduance.j2")

# gpt = LLM(api_key="37b6a23e010b4a1da5cec77107e0386b04f7c1e7544e4fb49dcb69686618125b", base_url=HKUST_BASE_URL)

def generate_prompt_for_long_COT_reasoning(sql_example, db_schemas):
    db_schema = None
    background = ""
    guiduance = ""
    for item in db_schemas:
        if item['database_name'] != sql_example['db']:
            continue
        else:
            db_schema = item
    if sql_example['label']:
        prompt = long_COT_prompt_template_for_normal_sql.format(sql = sql_example['sql'], db_schema = db_schema)
    if not sql_example['label']:
        ptype = sql_example['payload_template'].get('type', '') if isinstance(sql_example.get('payload_template', None), dict) else ''
        ptype_low = ptype.lower()
        if 'error' in ptype_low:
            background = background_for_Error_based_Attack
        elif 'union' in ptype_low:
            background = background_for_Union_query_Attack
        elif 'taut' in ptype_low:
            background = background_for_Tautologies_Attack
        elif 'piggy' in ptype_low or 'piggy-backed' in ptype_low or 'piggy backed' in ptype_low:
            background = background_for_Piggy_backed_Queries_Attack
        elif 'boolean' in ptype_low or 'boolean-based' in ptype_low:
            background = background_for_Boolean_based_Inference_Attack
        elif 'time' in ptype_low or 'time-based' in ptype_low:
            background = background_for_Time_based_Inference_Attack
        else:
            background = ""

        if sql_example['payload_template']['information_features'] == 'specific database':
            guiduance = advance_payload_anlysis_guiduance
        
        if guiduance != "":
            dynamic_step_order_1 = 7
            dynamic_step_order_2 = 8
        else:
            dynamic_step_order_1 = 6
            dynamic_step_order_2 = 7

        prompt = long_COT_prompt_template_for_injection_sql.format(backgound_for_certain_type_of_injection_attack = background, advance_payload_anlysis_guiduance = guiduance, dynamic_step_order_1 = dynamic_step_order_1, dynamic_step_order_2 = dynamic_step_order_2, sql =sql_example['sql'], db_schema = db_schema, payload = sql_example['payload'])
    
    return prompt

def generate_prompt_for_short_COT_reasoning(sql_example, db_schemas):
    db_schema = get_schema(db = sql_example['db'], schemas = db_schemas)
    if sql_example['label']:
        prompt = short_COT_prompt_template_for_normal_sql.format(sql = sql_example['sql'], db_schema = db_schema)
    if not sql_example['label']:
        prompt = short_COT_prompt_template_for_injection_sql.format( sql =sql_example['sql'], db_schema = db_schema, payload = sql_example['payload'])
    
    return prompt

def generate_COT_reasoning(prompt, sql_example, gpt):
    response = gpt.generate_by_hkust(prompt = prompt, model="gpt-4")
    return f"```json{{\"thinking\": \"{response}\", \"decision\": {sql_example['label']}}}```"











