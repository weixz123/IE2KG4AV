import tkinter as tk
from tkinter import scrolledtext, filedialog, ttk, messagebox
from neo4j import GraphDatabase
from openai import OpenAI
import json
import threading
import re
import os
import time
import hashlib
import pickle

# DeepSeek API 配置
client = OpenAI(
    api_key="sk-29790821bfe445b48334837e5f20bad1",
    base_url="https://api.deepseek.com",
)

# Neo4j 配置
NEO4J_CONFIG = {
    "uri": "bolt://localhost:7687",
    "auth": ("neo4j", "12345678"),
    "database": "neo4j"
}

# 缓存目录
CACHE_DIR = "extraction_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

class KnowledgeGraphApp:
    def __init__(self, root):
        self.root = root
        root.title("航空知识图谱构建器")
        root.geometry("1000x700")  # 更大的窗口以便更好地可视化
        
        # 初始化领域知识
        self.initialize_domain_knowledge()
        
        # GUI组件初始化
        self.create_widgets()
        
        # 连接到Neo4j
        self.driver = GraphDatabase.driver(
            NEO4J_CONFIG["uri"],
            auth=NEO4J_CONFIG["auth"]
        )
        
        # 处理状态
        self.is_processing = False
        self.current_filepath = None
        self.extracted_data = {
            "entities": set(),
            "relations": set(),
            "entity_types": set()
        }
        
    def initialize_domain_knowledge(self):
        # 飞行领域常见的实体类型和关系类型（作为建议，不是限制）
        self.suggested_entity_types = [
            "Aircraft", "Component", "System", "Procedure", "Regulation", 
            "Parameter", "Instrument", "Control", "Maneuver", "Phase", 
            "Warning", "Limit", "Checklist", "Condition", "Technique"
        ]
        
        self.suggested_relation_types = [
            "is_part_of", "controls", "monitors", "requires", "causes",
            "follows", "precedes", "connected_to", "affects", "operates_in",
            "measured_by", "performs", "indicates", "limits", "regulates"
        ]
        
    def create_widgets(self):
        # 主布局使用notebook选项卡
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 选项卡1: 知识抽取
        extraction_tab = ttk.Frame(self.notebook)
        self.notebook.add(extraction_tab, text="知识抽取")
        self.setup_extraction_tab(extraction_tab)
        
        # 选项卡2: 知识查询
        query_tab = ttk.Frame(self.notebook)
        self.notebook.add(query_tab, text="知识查询")
        self.setup_query_tab(query_tab)
        
        # 选项卡3: 设置
        settings_tab = ttk.Frame(self.notebook)
        self.notebook.add(settings_tab, text="设置")
        self.setup_settings_tab(settings_tab)
        
        # 状态栏
        self.status_bar = ttk.Frame(self.root)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.status_label = ttk.Label(self.status_bar, text="就绪")
        self.status_label.pack(side=tk.LEFT, padx=10)
        
        self.progress_bar = ttk.Progressbar(self.status_bar, mode="determinate", length=200)
        self.progress_bar.pack(side=tk.RIGHT, padx=10)
        
    def setup_extraction_tab(self, parent):
        # 文件选择
        file_frame = ttk.Frame(parent)
        file_frame.pack(pady=10, fill=tk.X)
        
        self.btn_select = ttk.Button(
            file_frame, text="选择文本文件", command=self.select_file)
        self.btn_select.pack(side=tk.LEFT)
        
        self.file_label = ttk.Label(file_frame, text="未选择文件")
        self.file_label.pack(side=tk.LEFT, padx=10)
        
        # 抽取选项
        options_frame = ttk.LabelFrame(parent, text="抽取选项")
        options_frame.pack(pady=10, fill=tk.X, padx=10)
        
        # 块大小选项
        chunk_frame = ttk.Frame(options_frame)
        chunk_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(chunk_frame, text="文本块大小:").pack(side=tk.LEFT)
        self.chunk_size_var = tk.StringVar(value="5000")
        chunk_size_entry = ttk.Entry(chunk_frame, textvariable=self.chunk_size_var, width=10)
        chunk_size_entry.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(chunk_frame, text="字符").pack(side=tk.LEFT)
        
        # 重叠选项
        overlap_frame = ttk.Frame(options_frame)
        overlap_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(overlap_frame, text="文本块重叠:").pack(side=tk.LEFT)
        self.overlap_var = tk.StringVar(value="500")
        overlap_entry = ttk.Entry(overlap_frame, textvariable=self.overlap_var, width=10)
        overlap_entry.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(overlap_frame, text="字符").pack(side=tk.LEFT)
        
        # 操作按钮
        action_frame = ttk.Frame(parent)
        action_frame.pack(pady=10, fill=tk.X)
        
        self.btn_extract = ttk.Button(
            action_frame, text="开始抽取", command=self.start_extraction, state=tk.DISABLED)
        self.btn_extract.pack(side=tk.LEFT)
        
        self.btn_stop = ttk.Button(
            action_frame, text="停止抽取", command=self.stop_extraction, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=10)
        
        # 结果显示
        results_frame = ttk.LabelFrame(parent, text="抽取结果")
        results_frame.pack(pady=10, fill=tk.BOTH, expand=True, padx=10)
        
        self.results_notebook = ttk.Notebook(results_frame)
        self.results_notebook.pack(fill=tk.BOTH, expand=True)
        
        # 实体选项卡
        entities_tab = ttk.Frame(self.results_notebook)
        self.results_notebook.add(entities_tab, text="实体")
        
        self.entities_area = scrolledtext.ScrolledText(
            entities_tab, wrap=tk.WORD, width=80, height=15)
        self.entities_area.pack(fill=tk.BOTH, expand=True)
        
        # 关系选项卡
        relations_tab = ttk.Frame(self.results_notebook)
        self.results_notebook.add(relations_tab, text="关系")
        
        self.relations_area = scrolledtext.ScrolledText(
            relations_tab, wrap=tk.WORD, width=80, height=15)
        self.relations_area.pack(fill=tk.BOTH, expand=True)
        
        # 日志选项卡
        log_tab = ttk.Frame(self.results_notebook)
        self.results_notebook.add(log_tab, text="日志")
        
        self.log_area = scrolledtext.ScrolledText(
            log_tab, wrap=tk.WORD, width=80, height=15)
        self.log_area.pack(fill=tk.BOTH, expand=True)
        
    def setup_query_tab(self, parent):
        # 查询输入
        query_frame = ttk.Frame(parent)
        query_frame.pack(pady=10, fill=tk.X)
        
        ttk.Label(query_frame, text="自然语言查询:").pack(side=tk.LEFT)
        
        self.query_entry = ttk.Entry(query_frame, width=50)
        self.query_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        self.btn_query = ttk.Button(
            query_frame, text="执行查询", command=self.execute_query)
        self.btn_query.pack(side=tk.LEFT, padx=10)
        
        # 生成的Cypher显示
        cypher_frame = ttk.LabelFrame(parent, text="生成的Cypher查询")
        cypher_frame.pack(pady=10, fill=tk.X, padx=10)
        
        self.cypher_area = scrolledtext.ScrolledText(
            cypher_frame, wrap=tk.WORD, width=80, height=5)
        self.cypher_area.pack(fill=tk.BOTH, expand=True)
        
        # 查询结果
        results_frame = ttk.LabelFrame(parent, text="查询结果")
        results_frame.pack(pady=10, fill=tk.BOTH, expand=True, padx=10)
        
        self.query_result_area = scrolledtext.ScrolledText(
            results_frame, wrap=tk.WORD, width=80, height=15)
        self.query_result_area.pack(fill=tk.BOTH, expand=True)
        
    def setup_settings_tab(self, parent):
        # Neo4j设置
        neo4j_frame = ttk.LabelFrame(parent, text="Neo4j设置")
        neo4j_frame.pack(pady=10, fill=tk.X, padx=10)
        
        # URI
        uri_frame = ttk.Frame(neo4j_frame)
        uri_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(uri_frame, text="URI:").pack(side=tk.LEFT)
        self.uri_var = tk.StringVar(value=NEO4J_CONFIG["uri"])
        uri_entry = ttk.Entry(uri_frame, textvariable=self.uri_var, width=40)
        uri_entry.pack(side=tk.LEFT, padx=5)
        
        # 用户名
        user_frame = ttk.Frame(neo4j_frame)
        user_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(user_frame, text="用户名:").pack(side=tk.LEFT)
        self.username_var = tk.StringVar(value=NEO4J_CONFIG["auth"][0])
        username_entry = ttk.Entry(user_frame, textvariable=self.username_var, width=20)
        username_entry.pack(side=tk.LEFT, padx=5)
        
        # 密码
        pass_frame = ttk.Frame(neo4j_frame)
        pass_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(pass_frame, text="密码:").pack(side=tk.LEFT)
        self.password_var = tk.StringVar(value=NEO4J_CONFIG["auth"][1])
        password_entry = ttk.Entry(pass_frame, textvariable=self.password_var, width=20, show="*")
        password_entry.pack(side=tk.LEFT, padx=5)
        
        # 数据库
        db_frame = ttk.Frame(neo4j_frame)
        db_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(db_frame, text="数据库:").pack(side=tk.LEFT)
        self.database_var = tk.StringVar(value=NEO4J_CONFIG["database"])
        database_entry = ttk.Entry(db_frame, textvariable=self.database_var, width=20)
        database_entry.pack(side=tk.LEFT, padx=5)
        
        # API设置
        api_frame = ttk.LabelFrame(parent, text="DeepSeek API设置")
        api_frame.pack(pady=10, fill=tk.X, padx=10)
        
        # API Key
        apikey_frame = ttk.Frame(api_frame)
        apikey_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(apikey_frame, text="API Key:").pack(side=tk.LEFT)
        self.apikey_var = tk.StringVar(value="sk-29790821bfe445b48334837e5f20bad1")
        apikey_entry = ttk.Entry(apikey_frame, textvariable=self.apikey_var, width=40, show="*")
        apikey_entry.pack(side=tk.LEFT, padx=5)
        
        # Base URL
        baseurl_frame = ttk.Frame(api_frame)
        baseurl_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(baseurl_frame, text="Base URL:").pack(side=tk.LEFT)
        self.baseurl_var = tk.StringVar(value="https://api.deepseek.com")
        baseurl_entry = ttk.Entry(baseurl_frame, textvariable=self.baseurl_var, width=40)
        baseurl_entry.pack(side=tk.LEFT, padx=5)
        
        # 保存按钮
        save_frame = ttk.Frame(parent)
        save_frame.pack(pady=20)
        
        self.btn_save = ttk.Button(
            save_frame, text="保存设置", command=self.save_settings)
        self.btn_save.pack()

    def save_settings(self):
        # 更新配置
        global NEO4J_CONFIG, client
        
        NEO4J_CONFIG = {
            "uri": self.uri_var.get(),
            "auth": (self.username_var.get(), self.password_var.get()),
            "database": self.database_var.get()
        }
        
        # 重新连接到Neo4j
        if hasattr(self, 'driver'):
            self.driver.close()
            
        self.driver = GraphDatabase.driver(
            NEO4J_CONFIG["uri"],
            auth=NEO4J_CONFIG["auth"]
        )
        
        # 更新API客户端
        client = OpenAI(
            api_key=self.apikey_var.get(),
            base_url=self.baseurl_var.get(),
        )
        
        messagebox.showinfo("设置", "设置已保存")

    def select_file(self):
        filepath = filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])
        if filepath:
            self.current_filepath = filepath
            filename = os.path.basename(filepath)
            self.file_label.config(text=filename)
            self.btn_extract.config(state=tk.NORMAL)
            self.log("已选择文件: " + filename)

    def start_extraction(self):
        if self.is_processing:
            return
            
        self.is_processing = True
        self.btn_extract.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        
        # 清除先前的结果
        self.entities_area.delete(1.0, tk.END)
        self.relations_area.delete(1.0, tk.END)
        self.log_area.delete(1.0, tk.END)
        
        # 重置提取的数据
        self.extracted_data = {
            "entities": set(),
            "relations": set(),
            "entity_types": set()
        }
        
        # 在单独的线程中开始处理
        threading.Thread(target=self.process_file, args=(self.current_filepath,)).start()

    def stop_extraction(self):
        self.is_processing = False
        self.btn_stop.config(state=tk.DISABLED)
        self.log("正在停止抽取过程...")

    def process_file(self, filepath):
        self.update_status("正在处理文件...")
        
        try:
            # 读取文件
            with open(filepath, 'r', encoding='utf-8') as f:
                text = f.read()
                
            # 获取块参数
            try:
                chunk_size = int(self.chunk_size_var.get())
                overlap = int(self.overlap_var.get())
            except ValueError:
                self.log("错误: 块大小和重叠必须是整数。使用默认值。")
                chunk_size = 5000
                overlap = 500
            
            # 将文本拆分为语义块
            chunks = self.split_text_semantic(text, chunk_size, overlap)
            total_chunks = len(chunks)
            
            self.log(f"文件已分割为 {total_chunks} 个块进行处理")
            self.progress_bar["maximum"] = total_chunks
            self.progress_bar["value"] = 0
            
            # 上下文窗口，用于块之间的交叉引用
            context = {
                "entities": {},  # name -> type 映射
                "relations": set(),  # (source, relation, target) 元组
                "entity_types": self.suggested_entity_types.copy(),  # 可拓展的实体类型列表
                "relation_types": self.suggested_relation_types.copy()  # 可拓展的关系类型列表
            }
            
            # 处理每个块
            for i, chunk in enumerate(chunks):
                if not self.is_processing:
                    break
                    
                self.update_status(f"处理段落 {i+1}/{total_chunks}")
                self.progress_bar["value"] = i
                self.root.update()
                
                # 为此块创建缓存键
                chunk_hash = hashlib.md5(chunk.encode('utf-8')).hexdigest()
                cache_file = os.path.join(CACHE_DIR, f"{chunk_hash}.pkl")
                
                # 检查是否有缓存的结果
                if os.path.exists(cache_file):
                    try:
                        with open(cache_file, 'rb') as f:
                            response = pickle.load(f)
                            self.log(f"块 {i+1} 使用缓存结果")
                    except Exception as e:
                        self.log(f"缓存加载错误: {str(e)}")
                        response = self.extract_entities_relations(chunk, context)
                        
                        # 缓存结果
                        with open(cache_file, 'wb') as f:
                            pickle.dump(response, f)
                else:
                    # 使用上下文提取实体和关系
                    response = self.extract_entities_relations(chunk, context)
                    
                    # 缓存结果
                    with open(cache_file, 'wb') as f:
                        pickle.dump(response, f)
                
                if response:
                    # 使用新的实体和关系更新上下文
                    for entity in response.get("entities", []):
                        context["entities"][entity["name"]] = entity["type"]
                        
                        # 更新实体类型集合（开放世界假设）
                        if entity["type"] not in context["entity_types"]:
                            context["entity_types"].append(entity["type"])
                            self.log(f"发现新实体类型: {entity['type']}")
                        
                    for relation in response.get("relations", []):
                        context["relations"].add((
                            relation["source"], 
                            relation["relation"], 
                            relation["target"]
                        ))
                        
                        # 更新关系类型集合（开放世界假设）
                        if relation["relation"] not in context["relation_types"]:
                            context["relation_types"].append(relation["relation"])
                            self.log(f"发现新关系类型: {relation['relation']}")
                    
                    # 保存到Neo4j
                    self.save_to_neo4j(response)
                    
                    # 更新UI
                    self.update_results(response)
                
                # 避免频率限制
                time.sleep(0.5)
            
            if self.is_processing:
                self.update_status("处理完成")
                self.log("知识图谱构建完成")
                
                # 显示统计信息
                self.log(f"共抽取 {len(self.extracted_data['entities'])} 个实体")
                self.log(f"共抽取 {len(self.extracted_data['relations'])} 条关系")
                self.log(f"实体类型: {', '.join(list(self.extracted_data['entity_types']))}")
            else:
                self.update_status("处理已中止")
                self.log("知识图谱构建已中止")
                
        except Exception as e:
            self.log(f"错误: {str(e)}")
            self.update_status("处理出错")
            
        finally:
            self.is_processing = False
            self.btn_extract.config(state=tk.NORMAL)
            self.btn_stop.config(state=tk.DISABLED)
            self.progress_bar["value"] = 0

    def split_text_semantic(self, text, max_length=5000, overlap=500):
        """
        将文本分割成语义块，尝试保留段落和章节。
        """
        # 首先，按明显的章节标记分割
        # 特别针对飞行手册的常见格式进行优化
        sections = re.split(r'(?:\r?\n){2,}|(?:\r?\n)(?=\d+\.\s|\w+\.\s|[A-Z][A-Z\s]+:|Chapter\s+\d+|Section\s+\d+)', text)
        
        chunks = []
        current_chunk = ""
        
        for section in sections:
            # 如果添加此部分超过max_length，存储当前块并开始一个新块
            if len(current_chunk) + len(section) > max_length and current_chunk:
                chunks.append(current_chunk)
                
                # 从前一个块的重叠开始新块
                if len(current_chunk) > overlap:
                    current_chunk = current_chunk[-overlap:] + "\n\n" + section
                else:
                    current_chunk = section
            else:
                if current_chunk:
                    current_chunk += "\n\n" + section
                else:
                    current_chunk = section
        
        # 如果不为空，添加最后一个块
        if current_chunk:
            chunks.append(current_chunk)
            
        return chunks

    def extract_entities_relations(self, text, context=None):
        """
        使用领域特定提示和上下文提取实体和关系。
        """
        # 为提示准备上下文
        context_info = ""
        if context and context["entities"]:
            # 列出一些已经找到的实体（为简洁起见，最多10个）
            entities_sample = list(context["entities"].items())[:10]
            entity_examples = "\n".join([f"- {name} (类型: {type_})" for name, type_ in entities_sample])
            if len(context["entities"]) > 10:
                entity_examples += f"\n(还有 {len(context['entities']) - 10} 个实体...)"
                
            # 包括发现的实体类型
            entity_types = ", ".join(context["entity_types"][:20])
            
            # 包括发现的关系类型
            relation_types = ", ".join(context["relation_types"][:20])
                
            context_info = f"""
已知实体示例:
{entity_examples}

已知实体类型:
{entity_types}

已知关系类型:
{relation_types}
"""

        # 飞行领域特定的提示，带有指导
        system_prompt = f"""
你是一个专业的航空领域知识图谱构建助手。请从以下文本中提取航空相关的实体和它们之间的关系。
基于开放世界假设，你可以发现新的实体类型和关系类型，而不仅限于已知的类型。

建议的实体类型（但不限于）:
{', '.join(self.suggested_entity_types)}

建议的关系类型（但不限于）:
{', '.join(self.suggested_relation_types)}

{context_info}

请注意:
1. 实体名称应当准确且具有明确含义
2. 实体类型应当尽可能具体，但可以创建新的类型
3. 关系应当明确表达两个实体间的语义联系
4. 专注于飞行技术中的概念、部件、程序和系统
5. 提取实体时考虑飞行器操作、安全程序和技术规范
6. 你应当捕获技术手册中的专业术语和标准程序
7. 可以发现新的术语、组件和关系类型（开放世界假设）
"""

        tools = [{
            "type": "function",
            "function": {
                "name": "extract_entities_relations",
                "description": "从航空领域文本中提取实体和关系",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entities": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "type": {"type": "string"},
                                    "description": {"type": "string", "description": "实体的简短描述或定义"},
                                    "confidence": {"type": "number", "description": "提取置信度(0-1)"}
                                },
                                "required": ["name", "type"]
                            }
                        },
                        "relations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "source": {"type": "string"},
                                    "target": {"type": "string"},
                                    "relation": {"type": "string"},
                                    "description": {"type": "string", "description": "关系的描述或上下文"},
                                    "confidence": {"type": "number", "description": "提取置信度(0-1)"}
                                },
                                "required": ["source", "target", "relation"]
                            }
                        }
                    }
                }
            }
        }]

        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"请分析以下航空领域文本并提取实体和关系:\n\n{text}"}
                ],
                tools=tools,
                tool_choice={"type": "function", "function": {"name": "extract_entities_relations"}}
            )

            if response.choices[0].message.tool_calls:
                args = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
                return args
                
        except Exception as e:
            self.log(f"抽取错误: {str(e)}")
            
        return None

    def save_to_neo4j(self, data):
        try:
            with self.driver.session(database=NEO4J_CONFIG["database"]) as session:
                # 创建实体，将类型作为标签使用
                for entity in data.get("entities", []):
                    # 准备属性
                    properties = {
                        "name": entity["name"]
                    }
                    
                    # 添加可选属性（如果存在）
                    if "description" in entity:
                        properties["description"] = entity["description"]
                    if "confidence" in entity:
                        properties["confidence"] = entity["confidence"]
                    
                    # 添加到已提取的实体集
                    self.extracted_data["entities"].add(entity["name"])
                    self.extracted_data["entity_types"].add(entity["type"])
                    
                    session.execute_write(
                        self.create_entity_with_type,
                        entity["type"],
                        properties
                    )
                
                # 创建关系
                for relation in data.get("relations", []):
                    # 准备属性
                    properties = {}
                    
                    # 添加可选属性（如果存在）
                    if "description" in relation:
                        properties["description"] = relation["description"]
                    if "confidence" in relation:
                        properties["confidence"] = relation["confidence"]
                    
                    # 添加到已提取的关系集
                    rel_tuple = (relation["source"], relation["relation"], relation["target"])
                    self.extracted_data["relations"].add(rel_tuple)
                    
                    session.execute_write(
                        self.create_relation,
                        relation["source"],
                        relation["target"],
                        relation["relation"],
                        properties
                    )
                    
        except Exception as e:
            self.log(f"Neo4j错误: {str(e)}")

    @staticmethod
    def create_entity_with_type(tx, entity_type, properties):
        # 转义标签中的任何非法字符
        safe_type = re.sub(r'[^a-zA-Z0-9_]', '_', entity_type)
        
        # 对名称进行参数化处理，避免注入
        name_param = properties["name"]
        
        # 构建属性参数字符串
        params = {}
        props_parts = []
        
        for i, (key, value) in enumerate(properties.items()):
            param_name = f"prop{i}"
            params[param_name] = value
            props_parts.append(f"{key}: ${param_name}")
            
        props_string = ", ".join(props_parts)
        params["name_param"] = name_param
        
        # 执行Cypher查询 - 使用动态标签
        query = f"""
        MERGE (e:{safe_type} {{name: $name_param}})
        SET e += {{{props_string}}}
        """
        
        tx.run(query, **params)

    @staticmethod
    def create_relation(tx, source, target, relation_type, properties=None):
        if properties is None:
            properties = {}
            
        # 转义关系类型中的任何非法字符
        safe_type = re.sub(r'[^a-zA-Z0-9_]', '_', relation_type)
        
        # 构建属性参数
        props_parts = []
        params = {
            "source": source,
            "target": target
        }
        
        for i, (key, value) in enumerate(properties.items()):
            param_name = f"prop{i}"
            params[param_name] = value
            props_parts.append(f"{key}: ${param_name}")
            
        props_clause = ""
        if props_parts:
            props_clause = f" SET r += {{{', '.join(props_parts)}}}"
            
        # 执行Cypher查询 - 根据名称匹配实体，使用动态关系类型
        query = f"""
        MATCH (a {{name: $source}}), (b {{name: $target}})
        MERGE (a)-[r:{safe_type}]->(b)
        {props_clause}
        """
        
        tx.run(query, **params)

    def update_results(self, data):
        # 更新实体区域
        for entity in data.get("entities", []):
            entity_str = f"{entity['name']} (类型: {entity['type']})"
            if "description" in entity:
                entity_str += f", 描述: {entity['description']}"
            if "confidence" in entity:
                entity_str += f", 置信度: {entity['confidence']:.2f}"
            
            self.entities_area.insert(tk.END, entity_str + "\n")
            self.entities_area.see(tk.END)
            
        # 更新关系区域
        for relation in data.get("relations", []):
            rel_str = f"{relation['source']} --[{relation['relation']}]--> {relation['target']}"
            if "description" in relation:
                rel_str += f", 描述: {relation['description']}"
            if "confidence" in relation:
                rel_str += f", 置信度: {relation['confidence']:.2f}"
            
            self.relations_area.insert(tk.END, rel_str + "\n")
            self.relations_area.see(tk.END)

    def execute_query(self):
        query_text = self.query_entry.get()
        if not query_text:
            return
            
        threading.Thread(target=self.nlp_query, args=(query_text,)).start()

    def nlp_query(self, question):
        self.update_status("正在处理查询...")
        
        try:
            # 生成Cypher查询
            cypher = self.generate_cypher(question)
            if cypher:
                # 显示生成的Cypher
                self.cypher_area.delete(1.0, tk.END)
                self.cypher_area.insert(tk.END, cypher)
                
                # 执行查询
                result = self.run_cypher_query(cypher)
                self.display_result(result)
                
            self.update_status("查询完成")
            
        except Exception as e:
            self.update_status("查询出错")
            self.display_result(f"错误: {str(e)}")

    def generate_cypher(self, question):
        # 查询生成的增强系统提示
        system_prompt = f"""
你是一个专业的航空知识图谱查询助手。你需要将自然语言问题转换为Neo4j的Cypher查询语句。

知识图谱结构:
1. 实体标签: 使用实体类型作为标签 (例如: Aircraft, Component, System)
2. 实体属性: name (实体名称), description (可选, 实体描述), confidence (可选, 提取置信度)
3. 关系类型: 动态的关系类型 (例如: is_part_of, controls, requires)
4. 关系属性: description (可选, 关系描述), confidence (可选, 提取置信度)

已知的实体类型示例:
{', '.join(list(self.extracted_data['entity_types'])[:20] if self.extracted_data['entity_types'] else self.suggested_entity_types)}

已提取的部分实体示例:
{', '.join(list(self.extracted_data['entities'])[:20])}

生成的Cypher查询应该:
1. 正确理解用户的意图
2. 使用上述图谱结构
3. 使用MATCH和WHERE子句查找实体和关系
4. 返回易于理解的结果
5. 处理可能的模糊查询情况
6. 支持路径查询、属性过滤和关系查询
"""

        tools = [{
            "type": "function",
            "function": {
                "name": "generate_cypher",
                "description": "将自然语言转换为Cypher查询语句",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cypher": {
                            "type": "string",
                            "description": "生成的Cypher查询语句"
                        },
                        "explanation": {
                            "type": "string",
                            "description": "查询语句的解释"
                        }
                    },
                    "required": ["cypher"]
                }
            }
        }]

        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"请将以下问题转换为Cypher查询:\n\n{question}"}
                ],
                tools=tools,
                tool_choice={"type": "function", "function": {"name": "generate_cypher"}}
            )

            if response.choices[0].message.tool_calls:
                args = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
                if "explanation" in args:
                    self.log(f"查询解释: {args['explanation']}")
                return args.get("cypher")
                
        except Exception as e:
            self.log(f"Cypher生成错误: {str(e)}")
            
        return None

    def run_cypher_query(self, cypher):
        try:
            with self.driver.session(database=NEO4J_CONFIG["database"]) as session:
                result = session.run(cypher)
                return [dict(record) for record in result]
        except Exception as e:
            return f"查询错误: {str(e)}"

    def display_result(self, result):
        self.query_result_area.delete(1.0, tk.END)
        
        if isinstance(result, list):
            if not result:
                self.query_result_area.insert(tk.END, "没有找到结果")
            else:
                for item in result:
                    # 格式化节点和关系
                    formatted_item = {}
                    for k, v in item.items():
                        if hasattr(v, 'labels') and hasattr(v, 'get'):  # Node object
                            formatted_item[k] = {
                                "labels": list(v.labels),
                                "properties": dict(v)
                            }
                        elif hasattr(v, 'type') and hasattr(v, 'start_node'):  # Relationship object
                            formatted_item[k] = {
                                "type": v.type,
                                "properties": dict(v)
                            }
                        else:
                            formatted_item[k] = v
                            
                    self.query_result_area.insert(
                        tk.END, 
                        json.dumps(formatted_item, indent=2, ensure_ascii=False) + "\n\n"
                    )
        else:
            self.query_result_area.insert(tk.END, str(result))

    def update_status(self, message):
        self.status_label.config(text=message)
        self.root.update_idletasks()

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.log_area.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_area.see(tk.END)
        self.root.update_idletasks()

    def on_close(self):
        if hasattr(self, 'driver'):
            self.driver.close()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = KnowledgeGraphApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()