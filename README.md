# 小说爬虫项目

这是一个使用 Python + Playwright + DeepSeek API 开发的小说爬虫项目，用于爬取笔趣阁网站的小说内容，并进行内容处理和存储。

## 功能特点

- 使用 Playwright 进行网页爬取
- 基于 DeepSeek API 的智能化爬虫控制流程
- 自动识别和解析网页内容，无需手动配置选择器
- 自动清理小说内容，去除广告等无关内容
- 使用 DeepSeek API 生成章节摘要
- 支持中英文双语内容（自动翻译）
- 本地文件存储和 MySQL 数据库存储
- 异步处理，提高爬取效率

## 工作原理

该爬虫采用 AI 引导的方式进行网页抓取：

1. Playwright 访问小说网站页面
2. DeepSeek API 分析页面内容，识别页面类型和关键元素
3. DeepSeek API 决定下一步行动（点击元素、提取内容、滚动页面等）
4. 程序执行 DeepSeek 推荐的操作
5. 重复以上步骤，直到完成所有章节的抓取

这种方式无需针对特定网站定制爬虫规则，可以自动适应不同的网站结构。

## 环境要求

- Python 3.8+
- MySQL 数据库
- DeepSeek API 密钥

## 安装步骤

1. 克隆项目并安装依赖：

```bash
git clone <repository_url>
cd novel-crawler
pip install -r requirements.txt
```

2. 安装 Playwright：

```bash
playwright install
```

3. 配置环境变量：

创建 `.env` 文件并填入以下配置：

```
DB_HOST=your_db_host
DB_PORT=3306
DB_NAME=novel
DB_USER=your_username
DB_PASSWORD=your_password
DEEPSEEK_API_KEY=your_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-ai/DeepSeek-R1-Distill-Llama-8B
```

## 使用方法

1. 修改 `crawler.py` 中的 `novel_url` 为要爬取的小说 URL

2. 运行爬虫：

```bash
python crawler.py
```

## 项目结构

```
.
├── README.md
├── requirements.txt
├── config.py           # 配置文件
├── database.py         # 数据库操作
├── deepseek_client.py  # DeepSeek API 客户端
└── crawler.py          # 爬虫主程序
```

## 数据库结构

### novel 表

- id: 小说 ID
- title: 小说标题
- author: 作者
- description: 描述
- source_url: 来源 URL
- category_id: 分类 ID
- created_at: 创建时间

### novel_chapter 表

- id: 章节 ID
- novel_id: 小说 ID
- chapter_index: 章节序号
- chapter_title: 章节标题
- chapter_summary: 章节摘要
- chapter_content_cn: 中文内容
- chapter_content_en: 英文内容
- chapter_url: 章节 URL
- created_at: 创建时间

## 注意事项

1. 请遵守网站的爬虫协议
2. 适当设置爬取间隔，避免对目标网站造成压力
3. 注意保护 API 密钥和数据库凭据
4. DeepSeek API 调用会产生费用，请注意控制使用量

## License

MIT
