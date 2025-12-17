

from utils.json_operation import *
from Attacker.Attacker import Attacker
import random

payload_template_path = "D:\\project\\SQLI-main\\SQLI-main\\data\\data_for_generate_injection_sql\\payloads.json"
train_sqls_path = 'D:\\project\\SQLI-main\\SQLI-main\\data\\normal_sqls\\train_sqls.json'

def get_single_key_of_payload_template(data_item):
    type = data_item['type']
    information_features = data_item['information_features']
    key = f"{type}||{information_features}"
    return key

def cluster_payload_templates(datas):
    clusters = dict()
    for item in datas:
        key = get_single_key_of_payload_template(item)
        if key not in clusters:
            clusters[key] = []
        clusters[key].append(item)
    
    return clusters

def get_single_key_of_injection_sql(data_item):
    type = data_item['payload_template']['type']
    annotator = data_item['original_sql']['annotator']
    information_features = data_item['payload_template']['information_features']
    comment = data_item.get('comment')
    key = f"{type}||{annotator}||{information_features}||{comment}"
    return key

def cluster_injection_sqls(datas):
    clusters = dict()
    for item in datas:
        key = get_single_key_of_injection_sql(item)
        if key not in clusters:
            clusters[key] = []
        clusters[key].append(item)
    
    return clusters

if __name__ == "__main__":

    payloads = read_json_file(payload_template_path)
    train_sqls = read_json_file(train_sqls_path)

    train_injection_sqls = [sql for sql in train_sqls if not sql['label']]
    payload_template_clusters = cluster_payload_templates(payloads)
    injection_sql_clusters = cluster_injection_sqls(train_injection_sqls)
    
    cluster_list=list(injection_sql_clusters.keys())
    # clusters_reward_distribution = {key: random.random() for key in injection_sql_clusters}

    # attacker = Attacker(number_of_training_sqls=100, rate_of_injection_sqls=0.3, cluster_list=cluster_list, normal_sqls_path='data/normal_sqls/normal_sqls.json', raw_datas_dir='data/data_for_generate_injection_sql')
    
    # attacker.update_clusters_probability_distribution(gamma=0.1, clusters_reward_distribution=clusters_reward_distribution)
    
    # selected_clusters = attacker.select_payload_template(k=5)
    
    
    for cluster in cluster_list:
        print(cluster, "\n")

    
    



