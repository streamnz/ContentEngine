import json
import time
import datetime
import re
import traceback
import logging
import os
import hashlib
import anthropic
from config import CLAUDE_CONFIG

logger = logging.getLogger(__name__)

class ClaudeClient:
    def __init__(self):
        self.client = anthropic.Anthropic(
            api_key=CLAUDE_CONFIG['api_key']
        )
        self.model = CLAUDE_CONFIG['model']
        # 用于统计API调用
        self.api_calls_count = 0
        self.total_time_spent = 0
        
        # 增加缓存功能
        self.cache_dir = 'cache/claude'
        os.makedirs(self.cache_dir, exist_ok=True)
        self.cache_hits = 0
        
        # Token限制设置，基于Claude 3.5 Sonnet的规格
        self.max_input_tokens_per_minute = 40000  # 每分钟最大输入tokens
        self.max_output_tokens_per_minute = 8000  # 每分钟最大输出tokens
        self.max_output_tokens_per_request = 4096  # 单次请求最大输出tokens
        
        # HTML压缩选项 - 基于token而非字节
        self.compress_html = True
        self.html_max_tokens = 30000  # 目标HTML最大tokens数

    def _get_cache_key(self, url, html_size):
        """生成缓存的键，基于URL和HTML大小"""
        key = f"{url}_{html_size}"
        return hashlib.md5(key.encode()).hexdigest()

    def _get_from_cache(self, cache_key):
        """暂时禁用缓存"""
        logger.info("缓存功能已临时禁用")
        return None

    def _save_to_cache(self, cache_key, data):
        """保存结果到缓存"""
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.json")
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"已保存到缓存: {cache_key}")
        except Exception as e:
            logger.error(f"保存缓存失败: {str(e)}")

    def _optimize_html(self, html):
        """暂时不压缩HTML，直接返回完整内容"""
        logger.info(f"HTML内容大小: {len(html)} 字符，不进行截取或压缩")
        return html  # 直接返回完整HTML，不做任何处理

    def clean_chapter_title(self, title):
        """清理章节标题，去除求收藏、推荐等字样"""
        if not title:
            return ""
            
        # 清理常见的干扰词
        cleaned_title = title
        patterns_to_remove = [
            r'（求收藏.*?）', r'\(求收藏.*?\)', 
            r'（求推荐.*?）', r'\(求推荐.*?\)',
            r'（新书.*?）', r'\(新书.*?\)',
            r'（加更.*?）', r'\(加更.*?\)',
            r'求.{0,4}?订阅', r'求.{0,4}?收藏', r'求.{0,4}?推荐',
            r'_.*? - 笔趣阁', r' - 笔趣阁'
        ]
        
        for pattern in patterns_to_remove:
            cleaned_title = re.sub(pattern, '', cleaned_title)
        
        # 去除多余空格并整理格式
        cleaned_title = re.sub(r'\s+', ' ', cleaned_title).strip()
        return cleaned_title

    def call_claude(self, prompt, url=None, html_size=None):
        """调用Claude API，返回纯文本响应，使用流式处理处理长输出"""
        self.api_calls_count += 1
        current_call = self.api_calls_count
        
        # 记录开始时间
        start_time = time.time()
        start_datetime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        logger.info(f"Claude调用 #{current_call} 开始时间: {start_datetime}")
        logger.info(f"Claude调用 #{current_call} 提示词长度: {len(prompt)} 字符")
        
        try:
            # 构建请求数据
            request_data = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": CLAUDE_CONFIG["max_output_tokens"],
                "stream": True  # 启用流式处理以支持长时间运行
            }
            
            # 发送流式请求
            with self.client.messages.stream(**request_data) as stream:
                message = stream.get_final_message()  # 等待流完成并获取完整消息
            
            # 计算耗时
            total_time = time.time() - start_time
            self.total_time_spent += total_time
            
            # 记录详细的响应信息
            logger.info(f"Claude调用 #{current_call} 完整响应:")
            logger.info(f"模型: {self.model}")
            
            # 详细记录token使用情况
            prompt_tokens = message.usage.input_tokens
            completion_tokens = message.usage.output_tokens
            total_tokens = prompt_tokens + completion_tokens
            logger.info(f"Claude调用 #{current_call} Token使用情况:")
            logger.info(f"  - 输入token数: {prompt_tokens}")
            logger.info(f"  - 输出token数: {completion_tokens}")
            logger.info(f"  - 总token数: {total_tokens}")
            
            if message.content and len(message.content) > 0:
                result = message.content[0].text
                
                # 打印完整响应内容长度
                logger.info(f"Claude调用 #{current_call} 完整响应内容长度: {len(result)} 字符")
                
                if not result or len(result.strip()) == 0:
                    logger.error(f"Claude调用 #{current_call} 响应内容为空")
                    return None
                
                # 估算输出token
                output_tokens_estimate = len(result) // 4  # 粗略估计
                logger.info(f"Claude调用 #{current_call} 输出token数估计: {output_tokens_estimate}")
                logger.info(f"Claude调用 #{current_call} 耗时: {total_time:.2f}秒")
                
                return result
                
        except Exception as e:
            logger.error(f"Claude调用 #{current_call} 发生异常")
            logger.error(f"异常信息: {str(e)}")
            logger.error(f"异常详情: {traceback.format_exc()}")
            return None

    def _clean_json_comments(self, json_str):
        """清理JSON字符串中的注释和无效内容"""
        # 删除所有的行注释 (//...)
        json_str = re.sub(r'//.*?(\n|$)', '\n', json_str)
        
        # 删除多行注释块 (/* ... */)
        json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
        
        # 删除内容中的非标准JSON注释，如"// ...省略中间章节..."
        json_str = re.sub(r'// .*?(\n|$)', '\n', json_str)
        
        # 处理末尾的逗号问题
        json_str = re.sub(r',(\s*})', r'\1', json_str)
        json_str = re.sub(r',(\s*])', r'\1', json_str)
        
        return json_str
        
    def _extract_chapters_with_regex(self, text):
        """使用正则表达式直接从文本中提取章节信息，不依赖JSON解析"""
        chapters = []
        
        # 尝试多种可能的章节信息模式
        # 模式1：{"title": "标题", "url": "/look/xxxx/xx.html"}
        pattern1 = r'\"title\":\s*\"(.*?)\".*?\"url\":\s*\"(/look/\d+/\d+\.html)\"'
        matches1 = re.findall(pattern1, text, re.DOTALL)
        
        # 模式2：{"title": "标题", "selector": "选择器"}
        pattern2 = r'\"title\":\s*\"(.*?)\".*?\"selector\":\s*\"(.+?)\"'
        matches2 = re.findall(pattern2, text, re.DOTALL)
        
        # 模式3：普通文本格式 "章节标题 - /look/xxxx/xx.html"
        pattern3 = r'(第?\s*\d+\s*章.*?|.*?天后.*?|.*?后妈.*?|.*?豪门.*?|.*?女配.*?|.*?民宿.*?|.*?舍.*?|.*?少女.*?|.*?年代.*?|.*?书里.*?|真假.*?|[0-9]+\..*?)\s*[-—–]\s*(/look/\d+/\d+\.html)'
        matches3 = re.findall(pattern3, text, re.DOTALL)
        
        # 合并结果
        all_matches = matches1 + matches3
        seen_urls = set()
        
        for title, url in all_matches:
            # 清理标题和URL
            title = title.strip()
            url = url.strip()
            
            # 确保URL以/look/开头
            if url.startswith("/look/") and url not in seen_urls:
                seen_urls.add(url)
                chapters.append({"title": self.clean_chapter_title(title), "url": url})
        
        # 如果模式1和模式3没有找到章节，尝试处理模式2的结果
        if not chapters and matches2:
            for title, selector in matches2:
                title = title.strip()
                chapters.append({"title": self.clean_chapter_title(title), "selector": selector})
        
        return chapters

    def analyze_chapter_list(self, html, url=None, state=None):
        """分析章节列表页面，提取所有章节信息"""
        prompt = f"""你是一个网页分析专家。请分析以下小说网站的HTML内容，提取所有章节链接信息。

请完成以下任务：
1. 找出所有章节的标题和链接URL (网址格式为：/look/数字/数字.html)
2. 查找展开全部章节的按钮选择器（如果存在）

重要说明：HTML中已经包含了全部章节信息，无需考虑隐藏内容或额外点击"展开全部"按钮。

你可以用以下两种方式之一返回分析结果：

方式一：JSON格式
```json
{{
  "expand_button_selector": null,
  "chapters": [
    {{"title": "第1章 xxx", "url": "/look/12345/1.html"}},
    {{"title": "第2章 yyy", "url": "/look/12345/2.html"}},
    ...
  ]
}}
```

方式二：简单列表格式（每行一个章节）
```
章节标题 - 章节URL
第1章 xxx - /look/12345/1.html
第2章 yyy - /look/12345/2.html
...
```

重要提示：
1. 必须提取所有章节，不要遗漏任何章节
2. 如果章节列表很长（可能有200多章），请确保返回完整的列表
3. 所有章节的信息已在HTML中，无需假设有章节被隐藏
4. 请注意查找所有包含"/look/"路径的链接作为章节URL
5. 如果发现分页机制，请说明

HTML内容：
{html[:80000]}

如果章节数量超过100章，请继续查找后续章节：
{html[80000:150000]}
"""
        
        response = self.call_claude(prompt, url, len(html))
        if not response:
            return {"expand_button_selector": None, "chapters": []}
            
        try:
            # 检查response是否已经是字典类型（已解析过的JSON）
            if isinstance(response, dict):
                result_json = response
            else:
                # 如果是字符串，尝试解析JSON响应
                try:
                    # 先尝试直接解析
                    result_json = json.loads(response)
                except json.JSONDecodeError:
                    # 如果直接解析失败，尝试从文本中提取JSON
                    if "raw_response" in response:
                        # 如果是包含原始响应的字典
                        raw_text = response["raw_response"]
                        # 尝试从原始响应中提取JSON
                        json_match = re.search(r'```json\s*(.*?)\s*```', raw_text, re.DOTALL)
                        if json_match:
                            json_text = json_match.group(1)
                            cleaned_json = self._clean_json_comments(json_text)
                            result_json = json.loads(cleaned_json)
                        else:
                            # 如果没有找到JSON代码块，返回空结果
                            logger.error("无法从原始响应中提取JSON")
                            return {"expand_button_selector": None, "chapters": []}
                    else:
                        # 不是字典也不能解析为JSON，返回空结果
                        logger.error("无法解析响应为JSON")
                        return {"expand_button_selector": None, "chapters": []}
            
            # 记录提取的章节数量
            if "chapters" in result_json:
                chapters_count = len(result_json["chapters"])
                logger.info(f"Claude调用 #{self.api_calls_count} 提取章节数: {chapters_count}")
                
                # 打印所有章节标题，便于调试
                logger.info("提取的章节列表:")
                for chapter in result_json["chapters"]:
                    logger.info(f"  - {chapter.get('title', '未知标题')}")
            
            return result_json
        except Exception as e:
            logger.error(f"Claude调用 #{self.api_calls_count} JSON解析失败: {str(e)}")
            logger.error(f"异常详情: {traceback.format_exc()}")
            return {"expand_button_selector": None, "chapters": []} 

    def analyze_structured_data(self, structured_data, chapters_count):
        """分析预先提取的结构化章节数据"""
        # 从 structured_data 中提取章节信息
        chapter_lines = structured_data.split('\n')
        chapters = []
        
        # 提取已经存在的章节信息
        for line in chapter_lines:
            # 匹配章节行，格式为 "数字. 标题 - URL"
            match = re.search(r'\d+\.\s+(.+?)\s+-\s+(.+)', line)
            if match:
                title = match.group(1).strip()
                url = match.group(2).strip()
                chapters.append({"title": title, "url": url})
        
        # 如果已经有完整的章节列表，直接处理并返回
        if len(chapters) >= chapters_count - 5:  # 允许有少量误差
            logger.info(f"检测到完整章节列表 ({len(chapters)}章)，直接处理")
            
            # 构建标准化格式的结果
            result = ""
            for chapter in chapters:
                result += f"<<<CHAPTER_START>>>\n"
                result += f"标题：{self.clean_chapter_title(chapter['title'])}\n"
                result += f"链接：{chapter['url']}\n"
                result += f"<<<CHAPTER_END>>>\n\n"
            
            return result
            
        # 否则，调用大模型处理预览章节
        prompt = f"""分析以下从网页预提取的小说章节信息，生成章节目录。

提取的内容：
{structured_data}

要求：
1. 分析章节标题是否符合命名规律，并根据需要规范化标题
2. 确保返回完整章节列表（共{chapters_count}章）
3. 按照章节顺序排列输出结果

请以下面的格式返回每一章信息：
<<<CHAPTER_START>>>
标题：章节标题
链接：章节URL
<<<CHAPTER_END>>>

只需返回章节信息，无需附加任何评论或说明。
"""
        
        response = self.call_claude(prompt)
        return response
    
    def parse_chapters_from_response(self, response):
        """从LLM返回的文本响应中提取章节信息"""
        if not response:
            return []
            
        chapters = []
        
        # 尝试解析基于标记的输出
        pattern = r"<<<CHAPTER_START>>>(.*?)<<<CHAPTER_END>>>"
        matches = re.findall(pattern, response, re.DOTALL)
        
        if matches:
            for match in matches:
                title_match = re.search(r"标题[:：]\s*(.*?)(?:\n|$)", match)
                url_match = re.search(r"链接[:：]\s*(.*?)(?:\n|$)", match)
                
                if title_match and url_match:
                    title = title_match.group(1).strip()
                    url = url_match.group(1).strip()
                    chapters.append({
                        "title": self.clean_chapter_title(title),
                        "url": url
                    })
        else:
            # 备用解析方法：尝试匹配行模式 "标题 - URL"
            pattern = r"([^-]+)\s*-\s*(/\S+\.html)"
            matches = re.findall(pattern, response)
            
            for title, url in matches:
                chapters.append({
                    "title": self.clean_chapter_title(title.strip()),
                    "url": url.strip()
                })
                
        logger.info(f"成功从模型响应中解析出 {len(chapters)} 个章节")
        return chapters 