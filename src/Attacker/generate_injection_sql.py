from utils.yaml_operation import load_yaml_to_dict
from utils.LLM import LLM
from utils.j2_opeartion import load_prompt_template
import re
import random
from typing import Dict, List, Any
from datetime import time
from datetime import date, timedelta
import string
import pymysql

class SymbolChecker:
    def __init__(self):
        self.bracket_pairs = {
            '(': ')',
            '[': ']',
            '{': '}'
        }
        self.quote_symbols = ["'", '"', '`']
    
    def check_balanced(self, text):
        """检查所有符号是否平衡"""
        
        if not isinstance(text, str):
            return False, "当前SQL语句为None"
        
        stack = []
        quote_stack = []
        i = 0
        
        while i < len(text):
            char = text[i]
            
            # 检查转义字符
            if i > 0 and text[i-1] == '\\':
                i += 1
                continue
            
            # 如果当前在引号内，只关心引号的闭合
            if quote_stack:
                if char == quote_stack[-1]:
                    quote_stack.pop()
                i += 1
                continue
            
            # 处理引号
            if char in self.quote_symbols:
                quote_stack.append(char)
            
            # 处理括号
            elif char in self.bracket_pairs:
                stack.append(char)
            elif char in self.bracket_pairs.values():
                if not stack:
                    return False, f"位置 {i}: 多余的闭合符号 '{char}'"
                
                last_open = stack.pop()
                if self.bracket_pairs[last_open] != char:
                    return False, f"位置 {i}: 符号不匹配 '{last_open}' 和 '{char}'"
            
            i += 1
        
        # 检查剩余的符号
        errors = []
        if stack:
            errors.append(f"未闭合的括号: {stack}")
        if quote_stack:
            errors.append(f"未闭合的引号: {quote_stack}")
        
        if errors:
            return False, "; ".join(errors)
        
        return True, "所有符号都已正确闭合"

class GetRandomAttribute:
    @staticmethod
    def random_time() -> str:
        """生成随机时间（HH:MM:SS）"""
        hour = random.randint(0, 23)
        minute = random.randint(0, 59)
        second = random.randint(0, 59)
        return f"{hour:02d}:{minute:02d}:{second:02d}"

    @staticmethod
    def random_date(start_date: date | None = None,
                    end_date: date | None = None) -> str:
        """生成 start_date 和 end_date 之间的随机日期，格式 YYYY-MM-DD"""
        if start_date is None:
            start_date = date(2000, 1, 1)
        if end_date is None:
            end_date = date(2025, 12, 31)

        if start_date > end_date:
            raise ValueError("start_date 不能晚于 end_date")

        delta = end_date - start_date
        random_days = random.randint(0, delta.days)
        random_date = start_date + timedelta(days=random_days)
        return random_date.strftime('%Y-%m-%d')

    @staticmethod
    def random_hex_number() -> str:
        """生成随机十六进制数（字符串形式，如 0x1a2b3c）"""
        return hex(random.randint(0, 0xFFFFFFFF))

    @staticmethod
    def random_int_number(min_value: int = 0, max_value: int = 100) -> int:
        """生成随机整数"""
        return str(random.randint(min_value, max_value))

    @staticmethod
    def random_float_number(min_value: float = 0.0,
                            max_value: float = 10.0,
                            ndigits: int = 2) -> float:
        """生成随机浮点数，保留 ndigits 位小数"""
        value = random.uniform(min_value, max_value)
        return str(round(value, ndigits))

    @staticmethod
    def random_character() -> str:
        """生成随机字符（英文字母）"""
        return random.choice(string.ascii_letters)
  
class SpecificDatabaseTemplateFiller:
    
    TYPE_MAPPING = {
        'number': ['int', 'integer', 'bigint', 'smallint', 'tinyint', 
                   'real', 'float', 'double', 'numeric', 'decimal'],
        'string': ['varchar', 'char', 'text', 'nvarchar', 'nchar', 
                   'clob', 'blob', 'string'],
        'date': ['date', 'datetime', 'timestamp', 'time'],
        'boolean': ['bool', 'boolean', 'bit'],
        'all': None  # None 表示不限制
    }
    
    def __init__(self, db_schema: Dict, mysql_config: Dict[str, Any] = None):
        """
        初始化填充器
        
        Args:
            db_schema: 数据库schema字典
            mysql_config: MySQL配置字典，包含 host, port, user, password, database, charset
        """
        self.db_schema = db_schema
        self.db_name = db_schema.get('database_name', 'unknown')
        
        # MySQL配置
        if mysql_config is None:
            raise ValueError("必须提供 mysql_config 参数")
        self.mysql_config = mysql_config
        
        # 构建表信息
        self.tables_info = {}
        self.table_names = []
        
        for table in db_schema.get('tables', []):   
            table_name = table['table_name']
            self.table_names.append(table_name)
            
            columns = []
            column_types = {}
            
            for col in table.get('columns', []):
                col_name = col['column_name']
                col_type = col['data_type']
                columns.append(col_name)
                column_types[col_name] = col_type
            
            self.tables_info[table_name] = {
                'columns': columns,
                'types': column_types
            }
    
    def _get_mysql_connection(self):
        """创建MySQL连接"""
        try:
            connection = pymysql.connect(
                host=self.mysql_config['host'],
                port=self.mysql_config['port'],
                user=self.mysql_config['user'],
                password=self.mysql_config['password'],
                database=self.mysql_config['database'],
                charset=self.mysql_config.get('charset', 'utf8mb4'),
                cursorclass=pymysql.cursors.DictCursor
            )
            return connection
        except Exception as e:
            print(f"MySQL 连接失败: {e}")
            return None
    
    def fill_template(self, template_input, debug=False) -> str:
        if isinstance(template_input, str):
            template = template_input
            expected_types = []
            if debug:
                print("📝 输入类型: 字符串（无类型约束）")
        elif isinstance(template_input, dict):
            template = template_input.get('payload', '')
            expected_types = template_input.get('expected_types', [])
            if debug:
                print(f"📝 输入类型: 字典")
                print(f"📝 expected_types: {expected_types}")
        else:
            raise ValueError("template_input 必须是字符串或字典")
        
        if "$int$" in template:
            template = template.replace("$int$", GetRandomAttribute.random_int_number())
            expected_types = [item for item in expected_types if item != "integer"]
        
        if "$float$" in template:
            template = template.replace("$float$", GetRandomAttribute.random_float_number())
            expected_types = [item for item in expected_types if item != "float"]
        
        if "$hex$" in template:
            template = template.replace("$hex$", GetRandomAttribute.random_hex_number())
            expected_types = [item for item in expected_types if item != "hex"]
        
        if "$time$" in template:
            template = template.replace("$time$", GetRandomAttribute.random_time())
            expected_types = [item for item in expected_types if item != "time"]
            
        if "$character$" in template:
            template = template.replace("$character$", GetRandomAttribute.random_character())
            expected_types = [item for item in expected_types if item != "character"]
            
        if "$date$" in template:
            template = template.replace("$date$", GetRandomAttribute.random_date())
            expected_types = [item for item in expected_types if item != "date"]
        
        # Step 1: 解析模板，提取所有占位符
        placeholders = self._parse_marked_template(template)
        
        if debug:
            print(f"📝 占位符数量: {len(placeholders)}")
            for i, p in enumerate(placeholders):
                print(f"  {i}: {p['full_match']} (type={p['type']})")
        
        # Step 2: 验证并调整 expected_types 长度
        if expected_types:
            if len(expected_types) != len(placeholders):
                print(f"⚠️  警告: expected_types 长度 ({len(expected_types)}) "
                      f"与占位符数量 ({len(placeholders)}) 不匹配")
                print([placeholder['type'] for placeholder in placeholders])
                print(expected_types)
                print(template)
                print("\n")
                # 如果长度不匹配，用 'all' 填充或截断
                if len(expected_types) < len(placeholders):
                    expected_types.extend(['all'] * (len(placeholders) - len(expected_types)))
                else:
                    expected_types = expected_types[:len(placeholders)]
            
            # 为占位符分配类型约束
            for i, placeholder in enumerate(placeholders):
                placeholder['expected_type'] = expected_types[i]
                if debug:
                    print(f"  {placeholder['full_match']} → expected_type: {expected_types[i]}")
        else:
            # 如果没有提供 expected_types，默认为 'all'
            for placeholder in placeholders:
                placeholder['expected_type'] = 'all'
            if debug:
                print("⚠️  未提供 expected_types，所有占位符使用 'all'")
        
        # Step 3: 统计需要多少个表
        max_table_id = self._get_max_table_id(placeholders)
        
        # Step 4: 分配表并获取数据（带类型约束）
        table_assignments = self._assign_tables_with_types(max_table_id, placeholders, debug)
        
        # Step 5: 为每个占位符生成替换值
        replacement_values = []
        
        for i, placeholder in enumerate(placeholders):
            value = self._get_marked_replacement(placeholder, table_assignments, template_input['information_features'], debug)
            replacement_values.append(value)
            if debug:
                print(f"  {placeholder['full_match']} → {value}")
        
        # Step 6: 从后向前替换（避免位置偏移）
        result = template
        for placeholder, value in reversed(list(zip(placeholders, replacement_values))):
            result = (
                result[:placeholder['start']] + 
                value + 
                result[placeholder['end']:]
            )
        
        return result
    
    def _parse_marked_template(self, template: str) -> List[Dict]:
        """
        解析带标记的模板
        
        支持的格式:
        - $table_N$
        - $column_tN_M$
        - $sample_tN_M$
        """
        placeholders = []
        
        # 匹配所有占位符
        pattern = r'\$(\w+)\$'
        
        for match in re.finditer(pattern, template):
            full_match = match.group(0)
            content = match.group(1)
            
            placeholder = {
                'full_match': full_match,
                'start': match.start(),
                'end': match.end()
            }
            
            # 解析 $table_N$
            table_match = re.match(r'table_(\d+)', content)
            if table_match:
                placeholder['type'] = 'table'
                placeholder['table_id'] = table_match.group(1)
                placeholders.append(placeholder)
                continue
            
            # 解析 $column_tN_M$
            column_match = re.match(r'column_t(\d+)_(\d+)', content)
            if column_match:
                placeholder['type'] = 'column'
                placeholder['table_id'] = column_match.group(1)
                placeholder['column_id'] = column_match.group(2)
                placeholders.append(placeholder)
                continue
            
            # 解析 $sample_tN_M$
            sample_match = re.match(r'sample_t(\d+)_(\d+)', content)
            if sample_match:
                placeholder['type'] = 'sample'
                placeholder['table_id'] = sample_match.group(1)
                placeholder['column_id'] = sample_match.group(2)
                placeholders.append(placeholder)
                continue
            
            # 如果都不匹配，标记为未知类型
            placeholder['type'] = 'unknown'
            placeholder['content'] = content
            placeholders.append(placeholder)
        
        return placeholders
    
    def _get_max_table_id(self, placeholders: List[Dict]) -> int:
        """获取最大的表ID"""
        max_id = 0
        
        for p in placeholders:
            if 'table_id' in p:
                table_id = int(p['table_id'])
                max_id = max(max_id, table_id)
        
        return max_id
    
    def _can_table_satisfy_constraints(self, table_name: str, 
                                       type_constraints: Dict[str, str]) -> bool:
        """
        检查表是否能满足所有类型约束
        
        Args:
            table_name: 表名
            type_constraints: {column_id: expected_type}
        
        Returns:
            True 如果表能满足所有约束
        """
        if not type_constraints:
            return True
        
        table_info = self.tables_info[table_name]
        all_columns = table_info['columns']
        all_types = table_info['types']
        
        for column_id, expected_type in type_constraints.items():
            # 检查是否有符合类型的列
            filtered = self._filter_columns_by_type(all_columns, all_types, expected_type)
            if not filtered:
                return False
        
        return True
    
    def _assign_tables_with_types(self, table_count: int, placeholders: List[Dict], debug=False) -> Dict[str, Dict]:
        """
        为每个表ID分配实际的表（带类型约束）
        """
        # 收集每个表ID需要的类型约束
        table_type_constraints = {}  # {table_id: {column_id: expected_type}}
        
        for placeholder in placeholders:
            ptype = placeholder['type']
            
            # 只处理 column 和 sample（它们需要类型约束）
            if ptype in ['column', 'sample']:
                table_id = placeholder['table_id']
                column_id = placeholder['column_id']
                expected_type = placeholder.get('expected_type', 'all')
                
                if table_id not in table_type_constraints:
                    table_type_constraints[table_id] = {}
                
                # 记录该列ID的类型约束
                if column_id in table_type_constraints[table_id]:
                    existing = table_type_constraints[table_id][column_id]
                    if existing == 'all':
                        table_type_constraints[table_id][column_id] = expected_type
                    elif expected_type != 'all' and expected_type != existing:
                        if debug:
                            print(f"⚠️  警告: column_id {column_id} 有冲突的类型约束: "
                                  f"{existing} vs {expected_type}，使用 {existing}")
                else:
                    table_type_constraints[table_id][column_id] = expected_type
        
        if debug:
            print(f"📊 类型约束汇总: {table_type_constraints}")
        
        # 为每个表ID分配表
        assignments = {}
        used_tables = set()
        
        for i in range(1, table_count + 1):
            table_id = str(i)
            
            # 获取该表的类型约束
            type_constraints = table_type_constraints.get(table_id, {})
            
            # 🔥 改进：优先选择能满足类型约束的表
            max_attempts = 50  # 增加尝试次数
            selected_table = None
            
            # 先尝试找到满足约束的表
            for attempt in range(max_attempts):
                candidate = random.choice(self.table_names)
                
                # 检查是否已使用（如果表足够多）
                if len(self.table_names) >= table_count and candidate in used_tables:
                    continue
                
                # 🔥 检查表是否能满足类型约束
                if self._can_table_satisfy_constraints(candidate, type_constraints):
                    selected_table = candidate
                    used_tables.add(candidate)
                    break
            
            # 如果找不到满足约束的表，随机选择一个（兜底）
            if selected_table is None:
                if debug:
                    print(f"⚠️  警告: 找不到满足约束的表（table_id={table_id}），随机选择")
                selected_table = random.choice(self.table_names)
            
            # 获取表信息
            table_info = self.tables_info[selected_table]
            all_columns = table_info['columns']
            all_types = table_info['types']
            
            if debug:
                print(f"📋 表 {table_id} 分配: {selected_table}")
                print(f"   所有列: {all_columns}")
            
            # 为每个 column_id 筛选符合类型的列
            filtered_columns_by_id = {}
            for column_id, expected_type in type_constraints.items():
                filtered = self._filter_columns_by_type(
                    all_columns, all_types, expected_type
                )
                filtered_columns_by_id[column_id] = filtered
                
                if debug:
                    print(f"   column_id {column_id} (type={expected_type}): {filtered}")
            
            # 获取样本数据（从MySQL）
            samples = self._get_table_samples(selected_table, all_columns)
            
            assignments[table_id] = {
                'table': selected_table,
                'columns': all_columns,
                'types': all_types,
                'samples': samples,
                'column_map': {},
                'type_constraints': type_constraints,
                'filtered_columns': filtered_columns_by_id
            }
        
        return assignments
    
    def _filter_columns_by_type(self, columns: List[str], 
                                types: Dict[str, str], 
                                expected_type: str) -> List[str]:
        """
        根据期望类型过滤列
        """
        if expected_type == 'all' or expected_type == 'table':
            return columns  # 不限制类型
        
        # 获取允许的数据库类型
        allowed_db_types = self.TYPE_MAPPING.get(expected_type, [])
        if allowed_db_types is None:  # 'all' 的情况
            return columns
        
        # 过滤列
        filtered = []
        for col in columns:
            col_type = types.get(col, '').lower()
            
            # 检查列类型是否匹配
            type_matched = False
            for allowed_type in allowed_db_types:
                if col_type == allowed_type or col_type.startswith(allowed_type):
                    type_matched = True
                    break
            
            if type_matched:
                filtered.append(col)
        
        return filtered  # 🔥 不再兜底，返回空列表由上层处理
    
    def _get_table_samples(self, table: str, columns: List[str]) -> Dict[str, str]:
        """从MySQL数据库中获取表的样本数据（随机选择）"""
        connection = None
        try:
            connection = self._get_mysql_connection()
            if connection is None:
                return {col: 'NULL' for col in columns}
            
            with connection.cursor() as cursor:
                # 处理列名（可能包含特殊字符）
                quoted_columns = [f'`{col}`' for col in columns]
                columns_str = ', '.join(quoted_columns)
                
                # 读取前100行
                
                sql = f"SELECT {columns_str} FROM {self.db_name}.`{table}` LIMIT 100"
                cursor.execute(sql)
                rows = cursor.fetchall()
                
                if not rows:
                    return {col: 'NULL' for col in columns}
                
                # 为每一列收集所有非空值，然后随机选择
                samples = {}
                for col in columns:
                    # 收集该列的所有非空值
                    non_null_values = []
                    for row in rows:
                        value = row.get(col)
                        if value is not None and value != '':
                            non_null_values.append(str(value))
                    
                    # 如果有非空值，随机选择一个；否则使用 'NULL'
                    if non_null_values:
                        samples[col] = random.choice(non_null_values)
                    else:
                        samples[col] = 'NULL'
                
                return samples
                
        except Exception as e:
            print(f"  ⚠️  警告: 读取表 {table} 失败 ({e})")
            return {col: 'NULL' for col in columns}
        finally:
            if connection:
                connection.close()
 
    def _get_marked_replacement(self, placeholder: Dict, 
                               table_assignments: Dict, information_features: str, debug=False) -> str:
        """根据标记获取替换值（支持类型约束）"""
        ptype = placeholder['type']
        
        # 处理 $table_N$
        if ptype == 'table':
            table_id = placeholder['table_id']
            if table_id in table_assignments:
                table_name = table_assignments[table_id]['table']
                # 根据 information_features 决定是否添加数据库名前缀
                if information_features == "specific database":
                    return table_name
                else:
                    return f"{self.db_name}.{table_name}"
            return 'unknown_table'
        
        # 处理 $column_tN_M$
        if ptype == 'column':
            table_id = placeholder['table_id']
            column_id = placeholder['column_id']
            
            if table_id not in table_assignments:
                return 'unknown_column'
            
            table_data = table_assignments[table_id]
            
            # 检查是否已经为这个列ID分配了列名
            if column_id in table_data['column_map']:
                column_name = table_data['column_map'][column_id]
            else:
                # 使用类型过滤后的列
                if column_id in table_data['filtered_columns']:
                    available_columns = table_data['filtered_columns'][column_id]
                    if debug:
                        print(f"    🔍 使用过滤后的列: {available_columns}")
                else:
                    # 如果没有类型约束，使用所有列
                    available_columns = table_data['columns']
                    if debug:
                        print(f"    🔍 使用所有列: {available_columns}")
                
                if not available_columns:
                    # 🔥 如果过滤后没有列，使用所有列（兜底）
                    available_columns = table_data['columns']
                    if debug:
                        print(f"    ⚠️  过滤后无列，使用所有列: {available_columns}")
                
                column_name = random.choice(available_columns)
                table_data['column_map'][column_id] = column_name
                
                if debug:
                    print(f"    ✅ 选中列: {column_name} (type={table_data['types'].get(column_name)})")
            
            # 处理包含特殊字符的列名
            if ' ' in column_name or '-' in column_name or '(' in column_name:
                return f'`{column_name}`'
            
            return column_name
        
        # 处理 $sample_tN_M$
        if ptype == 'sample':
            table_id = placeholder['table_id']
            column_id = placeholder['column_id']
            
            if table_id not in table_assignments:
                return 'NULL'
            
            table_data = table_assignments[table_id]
            
            # 获取对应的列名（必须先有列名）
            if column_id not in table_data['column_map']:
                # 使用类型过滤后的列
                if column_id in table_data['filtered_columns']:
                    available_columns = table_data['filtered_columns'][column_id]
                else:
                    available_columns = table_data['columns']
                
                if not available_columns:
                    available_columns = table_data['columns']
                
                column_name = random.choice(available_columns)
                table_data['column_map'][column_id] = column_name
            else:
                column_name = table_data['column_map'][column_id]
            
            # 获取该列的样本值
            sample_value = table_data['samples'].get(column_name, 'NULL')
            
            if sample_value == 'NULL':
                return 'NULL'
            
            # 格式化样本值
            col_type = table_data['types'].get(column_name, 'varchar')
            return self._format_sample(sample_value, col_type)
        
        # 未知类型
        return placeholder.get('content', 'unknown')
    
    def _format_sample(self, sample: Any, data_type: str = 'varchar') -> str:
        """格式化样本数据"""
        if sample is None or sample == 'NULL':
            return 'NULL'
        
        data_type = data_type.lower()
        
        # 数值类型：不加引号
        if data_type in ['int', 'integer', 'double', 'float', 'real', 'numeric', 'decimal', 
                         'bigint', 'smallint', 'tinyint']:
            return str(sample)
        
        # 日期类型：加引号
        if data_type in ['date', 'datetime', 'timestamp', 'time']:
            return f"'{sample}'"
        
        # 字符串类型：加引号，转义单引号
        if isinstance(sample, str):
            # 如果是纯数字字符串，根据类型决定是否加引号
            if sample.replace('.', '').replace('-', '').isdigit():
                if data_type in ['varchar', 'char', 'text', 'nvarchar', 'nchar', 
                                 'clob', 'blob', 'string']:
                    escaped = sample.replace("'", "''")
                    return f"'{escaped}'"
                else:
                    return sample
            else:
                escaped = sample.replace("'", "''")
                return f"'{escaped}'"
        
        return str(sample)
    
    def test_connection(self) -> bool:
        connection = self._get_mysql_connection()
        if connection:
            connection.close()
            print(f"✓ MySQL 连接成功: {self.mysql_config['host']}:{self.mysql_config['port']}/{self.mysql_config['database']}")
            return True
        else:
            print(f"✗ MySQL 连接失败")
            return False

class SystemInformationTemplateFiller:
    
    def __init__(self, 
                 system_information_list: List[Dict[str, Any]], 
                 mysql_config: Dict[str, Any]):
        """
        初始化填充器
        
        Args:
            system_information_list: 系统信息列表，每个元素包含variable, type, description
            mysql_config: MySQL配置字典，包含 host, port, user, password, database
        """
        self.system_information_list = system_information_list
        self.mysql_config = mysql_config
        
        # 按类型分类系统信息，便于快速查找
        self.sysinfo_by_type = {
            'integer': [],
            'string': [],
            'all': []
        }
        self._categorize_system_information()
    
    def _categorize_system_information(self):
        """将系统信息按类型分类"""
        for info in self.system_information_list:
            info_type = info.get('type', 'string')
            if info_type == 'integer':
                self.sysinfo_by_type['integer'].append(info)
            elif info_type == 'string':
                self.sysinfo_by_type['string'].append(info)
            # all类型包含所有信息
            self.sysinfo_by_type['all'].append(info)
    
    def _query_mysql(self, sql: str) -> str:
        """
        执行 MySQL 查询
        
        Args:
            sql: SQL查询语句
            
        Returns:
            查询结果的字符串表示
        """
        connection = None
        try:
            # 建立连接
            connection = pymysql.connect(
                host=self.mysql_config['host'],
                port=self.mysql_config['port'],
                user=self.mysql_config['user'],
                password=self.mysql_config['password'],
                database=self.mysql_config['database'],
                charset=self.mysql_config.get('charset', 'utf8mb4'),
                cursorclass=pymysql.cursors.DictCursor
            )
            
            with connection.cursor() as cursor:
                cursor.execute(sql)
                result = cursor.fetchone()
                
                # 处理查询结果
                if result is None:
                    return ''
                
                # 如果是字典类型（DictCursor），获取第一个值
                if isinstance(result, dict):
                    first_value = next(iter(result.values())) if result else None
                    return str(first_value) if first_value is not None else ''
                # 如果是元组类型
                elif isinstance(result, tuple):
                    return str(result[0]) if result[0] is not None else ''
                else:
                    return str(result)
                
        except Exception as e:
            print(f"MySQL 查询失败 [{sql}]: {e}")
            return ''
        finally:
            if connection:
                connection.close()
    
    def _select_sample_for_system_information(self, system_information: str) -> str:
        """
        从数据库中获取系统信息的样本值
        
        Args:
            system_information: 系统信息变量或SQL语句
            
        Returns:
            查询结果的字符串表示
        """
        # 如果不包含SELECT，添加SELECT前缀
        if "SELECT" not in system_information.upper():
            sql = f"SELECT {system_information}"
        else:
            sql = system_information
        
        return self._query_mysql(sql)
    
    def _get_random_system_information(self, expected_type: str) -> str:
        """
        根据期望类型随机选择一个系统信息变量
        
        Args:
            expected_type: 期望的类型 ('integer', 'string', 'all')
            
        Returns:
            系统信息变量字符串
        """
        # 如果期望类型是all，可以从所有类型中选择
        if expected_type == 'all':
            candidates = self.sysinfo_by_type['all']
        else:
            candidates = self.sysinfo_by_type.get(expected_type, [])
        
        if not candidates:
            # 如果没有匹配的类型，返回一个默认值
            return "VERSION()" if expected_type == 'string' else "1"
        
        # 随机选择一个
        selected = random.choice(candidates)
        return selected['variable']
    
    def fill_template(self, template: Dict[str, Any]) -> str:
        payload = template['payload']
        expected_types = template.get('expected_types', [])
        
        # 记录已使用的系统信息
        used_sysinfo = []
        
        # 1. 替换 $sysInfo$ 占位符
        sysinfo_count = payload.count('$sysInfo$')
        for i in range(sysinfo_count):
            # 获取对应位置的期望类型
            if i < len(expected_types):
                expected_type = expected_types[i]
            else:
                expected_type = 'all'
            
            # 随机选择系统信息
            sysinfo = self._get_random_system_information(expected_type)
            used_sysinfo.append(sysinfo)
            
            # 替换第一个出现的$sysInfo$
            payload = payload.replace('$sysInfo$', sysinfo, 1)
        
        # 2. 替换 $sample$ 占位符
        # 如果有$sample$，使用最后一个系统信息的样本值
        if '$sample$' in payload and used_sysinfo:
            sample_value = self._select_sample_for_system_information(used_sysinfo[-1])
            # 如果sample_value是字符串类型（非纯数字），需要加引号
            if sample_value and not sample_value.replace('.', '').replace('-', '').isdigit():
                sample_value = f"'{sample_value}'"
            payload = payload.replace('$sample$', sample_value if sample_value else '0')
        
        # 3. 替换其他占位符
        # 替换 $int$
        while '$int$' in payload:
            payload = payload.replace('$int$', GetRandomAttribute.random_int_number(), 1)
        
        # 替换 $float$
        while '$float$' in payload:
            payload = payload.replace('$float$', GetRandomAttribute.random_float_number(), 1)
        
        # 替换 $hex$
        while '$hex$' in payload:
            payload = payload.replace('$hex$', GetRandomAttribute.random_hex_number(), 1)
        
        # 替换 $time$
        while '$time$' in payload:
            payload = payload.replace('$time$', f"'{GetRandomAttribute.random_time()}'", 1)
        
        # 替换 $date$
        while '$date$' in payload:
            payload = payload.replace('$date$', f"'{GetRandomAttribute.random_date()}'", 1)
        
        # 替换 $character$ (注意：原来是 #character$，现在统一为 $character$)
        while '$character$' in payload:
            payload = payload.replace('$character$', f"'{GetRandomAttribute.random_character()}'", 1)
        
        # 兼容旧格式 #character$
        while '#character$' in payload:
            payload = payload.replace('#character$', f"'{GetRandomAttribute.random_character()}'", 1)
        
        return payload
    
    def test_connection(self) -> bool:
        """
        测试数据库连接
        
        Returns:
            连接是否成功
        """
        try:
            connection = pymysql.connect(
                host=self.mysql_config['host'],
                port=self.mysql_config['port'],
                user=self.mysql_config['user'],
                password=self.mysql_config['password'],
                database=self.mysql_config['database'],
                charset=self.mysql_config.get('charset', 'utf8mb4')
            )
            connection.close()
            print(f"✓ MySQL 连接成功: {self.mysql_config['host']}:{self.mysql_config['port']}/{self.mysql_config['database']}")
            return True
        except Exception as e:
            print(f"✗ MySQL 连接失败: {e}")
            return False

mysql_config = load_yaml_to_dict("config/database_connection.yaml")
gpt = LLM(api_key="37b6a23e010b4a1da5cec77107e0386b04f7c1e7544e4fb49dcb69686618125b", base_url=HKUST_BASE_URL)
checker = SymbolChecker()

def pipeline(sql_example, payload_template, db_schemas, sys_schemas, system_vars, comment_list, comment_rate):
    
    def identify_difficulty(annotator, comment, information_features):
        if annotator and comment and information_features == "constant":
            return "simple"
        if annotator and not comment and information_features == "constant":
            return "simple"
        if not annotator and not comment and information_features == "constant":
            return "simple"
        
        if annotator and comment and information_features == "system information":
            return "medium"
        if annotator and not comment and information_features == "system information":
            return "medium"
        if not annotator and not comment and information_features == "system information":
            return "medium"
        if annotator and not comment and information_features == "specific database":
            return "medium"
        
        if annotator and comment and information_features == "specific database":
            return "hard"
        if not annotator and not comment and information_features == "specific database":
            return "hard"
    
    def generate_comment(payload_type, payload_template, payload, comment_list):
        comment_type_list = ["Rational explanation", "Irrelevant text dilution", "Authoritative statement"]
        selected_type = random.choice(comment_type_list)
        if selected_type == "Irrelevant text dilution":
            selected_comment_list = [comment for comment in comment_list if comment['type'] == "Irrelevant text dilution"]
            return random.choice(selected_comment_list)['comment']
        if selected_type == "Authoritative statement":
            selected_comment_list = [comment for comment in comment_list if comment['type'] == "Authoritative statement"]
            return random.choice(selected_comment_list)['comment']
        if selected_type == "Rational explanation":
            prompt = load_prompt_template("prompt_templates", "generate_comment.j2").render(payload_type = payload_type, payload_template = payload_template, payload = payload)
            return gpt.generate_by_hkust(prompt = prompt, model="gpt-4")

    def insert_payload(sql, payload):
        def remove_first_char(text):
            """删除第一个字符"""
            return text[1:] if text else text
        
        def insert_char_at_position(text, position, char):
            """在指定位置插入字符"""
            return text[:position] + char + text[position:]
        
        def remove_unnecessary_comments(sql_text):
            """移除不必要的注释符
            只在以下情况删除注释符：
            1. 注释符是最后两个字符
            2. 注释符后面只有空白字符（空格、制表符、换行等）
            """
            comment_matches = list(re.finditer(r'--', sql_text))
            
            if not comment_matches:
                return sql_text
            
            # 从后往前处理，避免位置偏移问题
            for match in reversed(comment_matches):
                comment_pos = match.start()
                comment_end = match.end()  # comment_end = comment_pos + 2
                
                # 情况1：注释符已经是最后两位
                if comment_end >= len(sql_text):
                    sql_text = sql_text[:comment_pos]
                    continue
                
                # 情况2：注释符后面的内容
                remaining_text = sql_text[comment_end:]
                
                # 只有当后面全是空白字符时才删除注释符
                if remaining_text.strip() == '':  # 后面只有空白字符，没有实际内容
                    sql_text = sql_text[:comment_pos]
                # 如果后面有实际内容，保留注释符不做任何处理
            
            return sql_text
        
        if not isinstance(sql, str) or not isinstance(payload, str):
            return None
        
        try:
            # 查找注入点
            matches = list(re.finditer(r'\$\$', sql))
            if not matches:
                return None
            
            positions = [match.start() for match in matches]
            
            # 检查注入点后的字符类型
            try:
                potential_quote = sql[positions[0] + 2]
                is_string_context = (potential_quote == "'")
            except IndexError:
                is_string_context = False
            
            # 根据上下文决定是否需要移除payload的第一个字符
            if is_string_context:
                injection_sql = sql.replace("$$", payload)
            else:
                new_payload = remove_first_char(payload)
                injection_sql = sql.replace("$$", new_payload)
            
            # 新增：去掉不必要的注释符
            injection_sql = remove_unnecessary_comments(injection_sql)
            
            # 检查符号平衡（只检查注释符之前的部分）
            checker = SymbolChecker()
            effective_sql = injection_sql.split('--')[0] if '--' in injection_sql else injection_sql
            result, message = checker.check_balanced(effective_sql)
            
            # 如果不平衡，尝试添加闭合括号
            if not result:
                comment_matches = list(re.finditer(r'--', injection_sql))
                if comment_matches:
                    bracket_pos = comment_matches[0].start()
                else:
                    bracket_pos = len(injection_sql)
                
                injection_sql = insert_char_at_position(injection_sql, bracket_pos, ')')
                
                # 再次去掉可能产生的不必要注释符
                injection_sql = remove_unnecessary_comments(injection_sql)
            
            return injection_sql
            
        except Exception as e:
            print(f"插入payload时出错: {e}")
            return None

    comment_flag = False
    mysql_config['database'] = sql_example['db']
    injection_sql_example = None
    
    if payload_template['expected_types'] == None:
        raw_payload = payload_template['payload']
    else:
        if payload_template['information_features'] == "system information":
            if "table" in payload_template['expected_types']:
                sys_schema = random.choice(sys_schemas)
                filler_for_specific_databse = SpecificDatabaseTemplateFiller(sys_schema, mysql_config)
                raw_payload = filler_for_specific_databse.fill_template(payload_template)
            else:
                filler_for_system_information = SystemInformationTemplateFiller(system_vars, mysql_config)
                raw_payload = filler_for_system_information.fill_template(payload_template)
        
        if payload_template['information_features'] == "specific database":
            schema = next((s for s in db_schemas if s['database_name'] == sql_example['db']), {})
            filler_for_specific_databse = SpecificDatabaseTemplateFiller(schema, mysql_config)
            raw_payload = filler_for_specific_databse.fill_template(payload_template)
    
    if random.random() < comment_rate:
        payload = str(raw_payload) + str(generate_comment(payload_template['type'], payload_template['payload'], raw_payload, comment_list))
        comment_flag = True
    else:
        payload = str(raw_payload)
        comment_flag = False
        
    if sql_example['sql'] == None or payload == None:
        return injection_sql_example
    
    injection_sql = insert_payload(sql_example['sql'], payload)
    effective_sql = injection_sql.split('--')[0]
    result, message = checker.check_balanced(effective_sql)

    if not result:
        print(f"'{effective_sql}'\n  -> {result}: {message}\n")
    else:
        injection_sql_example = {
            "sql": injection_sql,
            "original_sql": sql_example,
            "payload_template":payload_template,
            "payload":payload,
            "label":False,
            "comment":comment_flag,
            "difficulty": identify_difficulty(sql_example['annotator'], comment_flag, payload_template['information_features'])
        }
    return injection_sql_example

def batch_generate_injection_sqls(expected_exmaple_num, raw_sqls, payloads, db_schemas, sys_schemas, system_vars, comment_list, comment_rate):
    count = 0
    injection_sql_examples = []
    while count < expected_exmaple_num:
        injection_sql_example = pipeline(random.choice(raw_sqls), random.choice(payloads), db_schemas, sys_schemas, system_vars, comment_list, comment_rate)
        injection_sql_examples.append(injection_sql_example)
        count += 1
    return injection_sql_examples


# 生成测试集注入样本
# test_injection_sqls = batch_generate_injection_sqls(30, test_raw_sqls, test_payloads, db_schemas, sys_schemas, system_vars, comment_list = comment_list, comment_rate=0.3)




