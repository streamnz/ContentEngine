import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 数据库配置
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'database': os.getenv('DB_DATABASE', 'dps'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', '')
}

# DeepSeek配置
DEEPSEEK_CONFIG = {
    'api_key': os.getenv('DEEPSEEK_API_KEY'),
    'base_url': 'https://api.deepseek.com/v1',
    'model': os.getenv('DEEPSEEK_MODEL', 'deepseek-chat'),
    'max_input_tokens': 64000,  # 最大输入token限制
    'max_output_tokens': 8000,  # 最大输出token限制 (DeepSeek Chat的最大限制)
    'html_max_tokens': 64000,   # HTML处理的最大token数
    'token_rate': {
        'input': 2.0,  # 百万输入tokens价格（元）
        'output': 8.0  # 百万输出tokens价格（元）
    },
    'retries': 2,
    'response_format': None  # 不强制要求JSON格式
}

# Claude配置
CLAUDE_CONFIG = {
    'api_key': os.getenv('ANTHROPIC_API_KEY'),
    'model': os.getenv('CLAUDE_MODEL', 'claude-3-7-sonnet-20250219'),
    'max_input_tokens_per_minute': 200000,  # 每分钟最大输入token限制
    'max_output_tokens_per_minute': 64000,  # 每分钟最大输出token限制
    'max_input_tokens': 200000,  # 最大输入token限制
    'max_output_tokens': 64000,   # 单次请求最大输出token限制
    'html_max_tokens': 150000,   # HTML处理的最大token数
    'token_rate': {
        'input': 1.5,  # 百万输入tokens价格（元，估算）
        'output': 4.5  # 百万输出tokens价格（元，估算）
    },
    'retries': 2
}

# 通用配置
CRAWLER_CONFIG = {
    'headless': False,        # 浏览器是否无头模式
    'default_timeout': 30000, # 默认超时时间（毫秒）
    'retry_limit': 3,         # 重试次数
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36',
    'use_claude': False,      # 是否优先使用Claude，默认使用DeepSeek
    'use_apify': False,       # 是否使用Apify获取网页内容代替Playwright，默认不使用
    'compress_html': False,   # 是否压缩HTML
    'cache_enabled': True,    # 是否启用缓存
    'cache_ttl': 86400,       # 缓存有效期（秒）
    'log_level': 'INFO',      # 日志级别
    'output_dir': 'output',   # 输出目录
    'max_novels': 100,        # 最大小说数量限制
    'max_chapters': 10000,     # 最大章节数量限制
    'base_url': 'https://www.hetushu.com/book/4917/index.html',  # 默认测试URL
    'headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Connection': 'keep-alive'
    }
}

# 本地存储配置
STORAGE_CONFIG = {
    'base_path': 'data/novels',  # 小说存储的基础路径
    'save_to_file': True    # 是否保存到本地文件
}

# 提示词模板 - 使用字符串协议定义
PROMPT_TEMPLATES = {
    # 章节列表提取模板
    'chapter_list': """分析以下从网页预提取的小说章节信息，生成章节目录。

提取的内容：
{content}

要求：
1. 分析章节标题，找出命名规律并规范化标题
2. 返回每个章节的标题和链接
3. 按照章节顺序排列输出结果

请按以下格式输出每章信息：
<<<CHAPTER_START>>>
标题：章节标题
链接：章节URL
<<<CHAPTER_END>>>

处理完成后，请在最后添加：
<<<PROCESSING_COMPLETE>>>
    """,
    
    # 章节内容提取模板
    'chapter_content': """分析以下从网页提取的小说章节内容，提取正文并进行清理。

提取的内容：
{content}

要求：
1. 提取章节标题
2. 提取章节正文内容（去除广告、导航等无关内容）
3. 清理后的内容应当只保留小说正文

请按以下格式输出：
<<<CONTENT_START>>>
标题：章节标题
正文：
章节正文内容...
<<<CONTENT_END>>>

处理完成后，请在最后添加：
<<<PROCESSING_COMPLETE>>>
    """
}

# Cookie配置（可选）
COOKIES = []

# 是否使用 Apify 平台
USE_APIFY = True  # True=使用Apify，False=本地Playwright 

# Apify配置
APIFY_CONFIG = {
    'api_token': os.getenv('APIFY_TOKEN'),
    'actor_id': 'ChNuXurElMWvpbJB9',  # Cloudflare Web Scraper 的 Actor ID
    'proxy_groups': ['RESIDENTIAL'],  # 使用住宅代理
    'js_timeout': 30,  # JavaScript 执行超时时间（秒）
    'max_retries': 3,  # 最大重试次数
} 