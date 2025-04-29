import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 数据库配置
DB_CONFIG = {
    'host': 'ai-game.cfkuy6mi4nng.ap-southeast-2.rds.amazonaws.com',
    'port': 3306,
    'database': 'dps',
    'user': 'chenghao',
    'password': 'C1h2E3n4G5%^'
}

# DeepSeek API配置
DEEPSEEK_CONFIG = {
    'api_key': 'sk-276ae03648454b8fa00baed9d46fb28a',
    'base_url': 'https://api.deepseek.com/v1',
    'model': 'deepseek-chat'
}

# 爬虫配置
CRAWLER_CONFIG = {
    'base_url': 'https://www.bqgl.cc/look/7787/',  # 星门小说的URL
    'headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
}

# 本地存储配置
STORAGE_CONFIG = {
    'base_path': 'novels'  # 小说存储的基础路径
} 