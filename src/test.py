from Attacker.generate_injection_sql import batch_generate_injection_sqls
from utils.cluster import ClusterKey, cluster_injection_sqls
from utils.json_operation import read_json_file, write_json_file
import random

normal_sqls = read_json_file(r"data\raw_datas_for_generation\normal_sqls.json")
train_normal_sqls = [sql for sql in normal_sqls if sql['set'] == "train"]
test_normal_sqls = [sql for sql in normal_sqls if sql['set'] == "test"]

raw_sqls = read_json_file(r"data\raw_datas_for_generation\sql_data_with_injection_point.json")
train_raw_sqls = [sql for sql in raw_sqls if sql['set'] == "train"]
test_raw_sqls = [sql for sql in raw_sqls if sql['set'] == "test"]

payloads = read_json_file(r"data\raw_datas_for_generation\payloads.json")
train_payloads = [payload for payload in payloads if payload['set'] == "train"]
test_payloads = [payload for payload in payloads if payload['set'] == "test"]

db_schemas = read_json_file(r"data\raw_datas_for_generation\schema.json")
sys_schemas = read_json_file(r"data\raw_datas_for_generation\system_table_schema.json")
system_vars = read_json_file(r"data\raw_datas_for_generation\system_var.json")
comment_list = read_json_file(r"data\raw_datas_for_generation\comment_repository.json")


# train_injection_sqls = batch_generate_injection_sqls(expected_exmaple_num=3000, raw_sqls=train_raw_sqls, payloads=train_payloads, db_schemas=db_schemas, sys_schemas=sys_schemas, system_vars=system_vars, comment_list=comment_list, comment_rate=0.4)
# write_json_file("new_train_injection_sqls.json", train_injection_sqls)

# test_injection_sqls = batch_generate_injection_sqls(expected_exmaple_num=3000, raw_sqls=test_raw_sqls, payloads=test_payloads, db_schemas=db_schemas, sys_schemas=sys_schemas, system_vars=system_vars, comment_list=comment_list, comment_rate=0.4)
# write_json_file("new_test_injection_sqls.json", test_injection_sqls)

# train_injection_sqls = read_json_file(r"new_train_injection_sqls.json")
# test_injection_sqls = read_json_file(r"new_test_injection_sqls.json")

# train_sqls = train_injection_sqls + train_normal_sqls
# test_sqls = test_injection_sqls + test_normal_sqls

# random.shuffle(train_sqls)
# random.shuffle(test_sqls)

# write_json_file(r"train_sqls.json", train_sqls)
# write_json_file(r"test_sqls.json", test_sqls)

# print(len(train_normal_sqls))
# print(len(test_normal_sqls))




# train_injection_sqls = read_json_file(r"new_train_injection_sqls.json")
# train_injection_sqls_cluster = cluster_injection_sqls(train_injection_sqls)
# print(f"共得到 {len(train_injection_sqls_cluster)} 个聚类。")
# keys = train_injection_sqls_cluster.keys()
# for key in keys:
#     print(key, len(train_injection_sqls_cluster[key]))
# print(len(train_injection_sqls))

# print("="*100)

# test_injection_sqls = read_json_file(r"new_test_injection_sqls.json")
# test_injection_sqls_cluster = cluster_injection_sqls(test_injection_sqls)
# print(f"共得到 {len(test_injection_sqls_cluster)} 个聚类。")
# keys = test_injection_sqls_cluster.keys()
# for key in keys:
#     print(key, len(test_injection_sqls_cluster[key]))
# print(len(test_injection_sqls))




# train_injection_sqls = read_json_file(r"new_train_injection_sqls.json")

# comment = 0
# no_annotator = 0
# specific_database = 0

# for sql in train_injection_sqls:
#     if sql['comment']:
#         comment += 1
#     if not sql['original_sql']['annotator']:
#         no_annotator+=1
#     if sql['payload_template']['information_features'] == "specific database":
#         specific_database+=1
        
# print(comment/len(train_injection_sqls))
# print(no_annotator/len(train_injection_sqls))
# print(specific_database/len(train_injection_sqls))

# print("="*100)

# test_injection_sqls = read_json_file(r"new_test_injection_sqls.json")

# comment = 0
# no_annotator = 0
# specific_database = 0

# for sql in test_injection_sqls:
#     if sql['comment']:
#         comment += 1
#     if not sql['original_sql']['annotator']:
#         no_annotator+=1
#     if sql['payload_template']['information_features'] == "specific database":
#         specific_database+=1
        
# print(comment/len(test_injection_sqls))
# print(no_annotator/len(test_injection_sqls))
# print(specific_database/len(test_injection_sqls))