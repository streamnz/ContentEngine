import json
import time
import datetime
import re
import traceback
from openai import OpenAI
from config import DEEPSEEK_CONFIG
import logging

# 获取AI日志专用logger
ai_logger = logging.getLogger('ai')

class DeepSeekClient:
    def __init__(self):
        self.client = OpenAI(
            api_key=DEEPSEEK_CONFIG['api_key'],
            base_url=DEEPSEEK_CONFIG['base_url']
        )
        self.model = DEEPSEEK_CONFIG['model']
        # 用于统计Deepseek调用
        self.api_calls_count = 0
        self.total_time_spent = 0
        
        # 增加缓存功能
        self.cache = {}
        self.cache_hits = 0
        
        # Token限制设置，基于DeepSeek-chat的规格
        self.max_input_tokens = 64000  # 最大输入tokens
        self.max_output_tokens = 8000  # 最大输出tokens
        
        # HTML压缩选项 - 基于token而非字节
        self.compress_html = True
        self.html_max_tokens = 50000  # 目标HTML最大tokens数
        
        ai_logger.info("DeepSeek客户端初始化完成")

    def _optimize_html(self, html):
        """暂时不压缩HTML，直接返回完整内容"""
        html_size = len(html)/1024 if html else 0
        ai_logger.info(f"HTML大小: {html_size:.2f} KB，不进行压缩")
        return html  # 直接返回完整HTML，不做任何处理

    def _call_api(self, prompt, use_cache=False):
        """调用DeepSeek API接口，直接返回文本响应"""
        if not prompt:
            ai_logger.warning("提示词为空，取消API调用")
            return None
            
        self.api_calls_count += 1
        current_call = self.api_calls_count
        
        # 记录开始时间
        start_time = time.time()
        start_datetime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 记录调用信息
        ai_logger.info(f"DeepSeek调用 #{current_call} 开始")
        ai_logger.info(f"提示词长度: {len(prompt)} 字符")
        ai_logger.info(f"使用模型: {self.model}")
        
        try:
            # 初始化客户端
            client = OpenAI(
                api_key=DEEPSEEK_CONFIG["api_key"],
                base_url=DEEPSEEK_CONFIG["base_url"]
            )
            
            # 设置请求参数
            request_data = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": DEEPSEEK_CONFIG["max_output_tokens"],
                "response_format": None  # 直接返回文本，不强制JSON
            }
            
            # 发送API请求
            ai_logger.info(f"请求已发送，等待响应...")
            response = client.chat.completions.create(**request_data)
            
            # 提取响应文本
            response_text = response.choices[0].message.content
            
            # 计算耗时
            total_time = time.time() - start_time
            
            # 记录详细的响应信息
            ai_logger.info(f"DeepSeek调用 #{current_call} 已完成")
            
            # 详细记录token使用情况
            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens
            total_tokens = response.usage.total_tokens
            ai_logger.info(f"Token统计:")
            ai_logger.info(f"  输入: {prompt_tokens} tokens")
            ai_logger.info(f"  输出: {completion_tokens} tokens")
            ai_logger.info(f"  总计: {total_tokens} tokens")
            
            # 记录响应内容长度
            ai_logger.info(f"响应长度: {len(response_text)} 字符")
            ai_logger.info(f"总耗时: {total_time:.2f}秒")
            
            return response_text
            
        except Exception as e:
            # 记录异常
            total_time = time.time() - start_time
            ai_logger.error(f"DeepSeek调用 #{current_call} 发生异常: {str(e)}")
            ai_logger.error(f"异常详情: {traceback.format_exc()}")
            ai_logger.error(f"耗时: {total_time:.2f}秒")
            return None

    def _extract_chapters_with_regex(self, text):
        """使用正则表达式直接从文本中提取章节信息，不依赖JSON解析"""
        if not text:
            ai_logger.warning("文本为空，无法提取章节信息")
            return []
            
        chapters = []
        
        # 尝试多种可能的章节信息模式
        # 模式1：{"title": "标题", "url": "链接"}
        pattern1 = r'\"title\":\s*\"(.*?)\".*?\"url\":\s*\"(.*?)\"'
        matches1 = re.findall(pattern1, text, re.DOTALL)
        
        # 模式2："标题" - "/look/xxxx/xx.html"
        pattern2 = r'\"(.*?)\"[\s\-]*\"(/look/\d+/\d+\.html)\"'
        matches2 = re.findall(pattern2, text, re.DOTALL)
        
        # 模式3：普通文本格式 "章节标题 - /look/xxxx/xx.html"
        pattern3 = r'(第?\s*\d+\s*章.*?|.*?天后.*?|.*?后妈.*?|.*?豪门.*?|.*?女配.*?|.*?民宿.*?|.*?舍.*?|.*?少女.*?|.*?年代.*?|.*?书里.*?)\s*[-—–]\s*(/look/\d+/\d+\.html)'
        matches3 = re.findall(pattern3, text, re.DOTALL)
        
        # 合并结果
        all_matches = matches1 + matches2 + matches3
        seen_urls = set()
        
        for title, url in all_matches:
            # 清理标题和URL
            title = title.strip()
            url = url.strip()
            
            # 确保URL以/look/开头
            if url.startswith("/look/") and url not in seen_urls:
                seen_urls.add(url)
                chapters.append({"title": title, "url": url})
        
        ai_logger.info(f"正则提取章节: 模式1={len(matches1)}章, 模式2={len(matches2)}章, 模式3={len(matches3)}章")
        ai_logger.info(f"正则提取总计: {len(chapters)}章 (去重后)")
        
        return chapters

    def _extract_data_from_reasoner_response(self, text):
        """从DeepSeek Reasoner的响应中提取结构化数据"""
        ai_logger.info("从Reasoner响应提取结构化数据")
        
        # 1. 尝试直接从文本中提取JSON格式
        try:
            # 查找文本中的JSON格式
            import re
            json_pattern = r'\{[\s\S]*\}'
            json_match = re.search(json_pattern, text)
            if json_match:
                json_text = json_match.group(0)
                try:
                    return json.loads(json_text)
                except:
                    pass
        except:
            pass
            
        # 2. 提取小说标题
        title_match = re.search(r'(?:标题|书名|小说名|小说标题)[：:]\s*(.+?)\n', text)
        title = title_match.group(1) if title_match else "未知标题"
        
        # 3. 提取作者
        author_match = re.search(r'(?:作者|作家|作品作者)[：:]\s*(.+?)\n', text)
        author = author_match.group(1) if author_match else "未知作者"
        
        # 4. 提取简介
        desc_match = re.search(r'(?:简介|描述|内容概要|内容简介)[：:]\s*([\s\S]+?)(?=\n\n|\n章节列表)', text)
        description = desc_match.group(1).strip() if desc_match else ""
        
        # 5. 提取章节列表
        chapters = []
        
        # 尝试方法1：查找章节标题和URL的模式
        chapter_pattern = r'([^"]+?)(?:\s*[-—–]\s*|[：:]\s*|"\s+url[：:]\s*")([\/\w\.]+\.html)"'
        chapter_matches = re.finditer(chapter_pattern, text, re.IGNORECASE)
        
        for match in chapter_matches:
            title = match.group(1).strip()
            url = match.group(2).strip()
            if url and url.startswith('/look/'):
                chapters.append({"title": title, "url": url})
        
        # 如果方法1找不到章节，尝试方法2：查找一般格式的章节列表
        if not chapters:
            chapter_pattern = r'(?:第\s*\d+\s*章|第[一二三四五六七八九十百千]+章|[（\(]\d+[）\)])\s*(.+?)\s*(?:地址|URL|链接)[：:]\s*(.+?\.html)'
            chapter_matches = re.finditer(chapter_pattern, text, re.IGNORECASE)
            
            for match in chapter_matches:
                title = match.group(1).strip()
                url = match.group(2).strip()
                if url and url.startswith('/look/'):
                    chapters.append({"title": title, "url": url})
        
        # 构建结果数据结构
        result = {
            "page_type": "chapter_list",
            "title": title,
            "author": author,
            "description": description,
            "category_id": 7,  # 默认分类
            "category_name": "女生",  # 默认分类名
            "chapters": chapters
        }
        
        ai_logger.info(f"从Reasoner响应中提取到 {len(chapters)} 个章节")
        return result

    def _parse_json_response(self, response):
        """解析API返回的JSON，支持各种格式"""
        if not response:
            ai_logger.error("[解析] 响应为空")
            return None
            
        ai_logger.info(f"[解析] 尝试解析响应，长度: {len(response)} 字符")
        
        try:
            # 1. 如果有Markdown代码块，提取其中的JSON
            if "```json" in response:
                parts = response.split("```json")
                if len(parts) > 1:
                    json_part = parts[1].split("```")[0].strip()
                    try:
                        result = json.loads(json_part)
                        ai_logger.info(f"[解析] 成功从代码块解析JSON")
                        return result
                    except:
                        pass
            
            # 2. 尝试直接解析整个响应
            try:
                result = json.loads(response)
                ai_logger.info(f"[解析] 成功直接解析JSON")
                return result
            except:
                pass
            
            # 3. 查找并提取第一个完整的JSON对象
            start = response.find('{')
            end = response.rfind('}') + 1
            if start >= 0 and end > start:
                json_part = response[start:end]
                try:
                    result = json.loads(json_part)
                    ai_logger.info(f"[解析] 成功从文本中提取JSON")
                    return result
                except:
                    pass
            
            # 4. 如果都失败了，尝试从文本中提取关键信息
            ai_logger.warning("[解析] 无法解析JSON，尝试从文本提取信息")
            
            result = {
                "page_type": "unknown",
                "next_action": {
                    "action": "GO_BACK",
                    "description": "无法解析页面，返回上一页"
                }
            }
            
            # 根据关键词判断页面类型
            if any(kw in response for kw in ["目录", "章节列表", "首页"]):
                result["page_type"] = "chapter_list"
                result["next_action"] = {
                    "action": "CLICK_ELEMENT",
                    "selector": "a[href*='chapter']",
                    "description": "点击第一章链接"
                }
            elif any(kw in response for kw in ["正文", "内容", "下一章"]):
                result["page_type"] = "chapter_content"
                result["next_action"] = {
                    "action": "NEXT_CHAPTER",
                    "selector": "a:contains('下一章')",
                    "description": "前往下一章"
                }
            
            return result
            
        except Exception as e:
            ai_logger.error(f"[解析] 发生异常: {str(e)}")
            ai_logger.error(f"[解析] 异常详情: {traceback.format_exc()}")
            return None

    def generate_summary(self, text):
        """生成章节摘要"""
        if not text or len(text) < 100:
            return "内容过短，无法生成摘要"
            
        prompt = f"""请为以下小说章节内容生成一个简短的摘要（100字以内）：

{text[:10000]}
"""
        
        result = self._call_api(prompt)
        return result or "无法生成摘要"

    def translate_to_english(self, text):
        """将中文内容翻译成英文"""
        if not text or len(text) < 50:
            return "Content too short to translate."
            
        prompt = f"""请将以下中文文本翻译成英文：

{text[:5000]}
"""
        
        result = self._call_api(prompt)
        return result or "Translation unavailable."

    def clean_content(self, text):
        """清理文本内容，去除广告、作者说明等无关内容"""
        if not text or len(text) < 100:
            return text
            
        prompt = f"""请清理以下小说章节内容，只保留纯小说正文，去除所有的：
1. 广告
2. 月票请求
3. 作者说明
4. 请假通知
5. 其他与故事情节无关的内容

原文：

{text[:20000]}
"""
        
        result = self._call_api(prompt)
        return result or text  # 如果API失败，返回原始文本
    
    def analyze_webpage(self, html, state=None):
        """分析网页内容并给出下一步操作指令"""
        state_info = ""
        if state:
            state_info = f"""
当前爬虫状态：
{json.dumps(state, ensure_ascii=False)}
"""
        
        prompt = f"""请分析以下网页HTML内容，并以JSON格式返回分析结果。

你是一个智能网页分析助手，用于指导爬虫如何抓取小说内容。{state_info}

可能的操作包括：
1. CLICK_ELEMENT - 点击网页上的某个元素（需提供有效的CSS选择器）
2. EXTRACT_CONTENT - 提取当前页面的内容（小说信息、章节列表或章节内容）
3. SCROLL_DOWN - 向下滚动页面以加载更多内容
4. GO_BACK - 返回上一页
5. NEXT_CHAPTER - 前往下一章（需提供选择器或说明如何找到下一章）
6. FINISH_CRAWLING - 完成爬取

示例JSON输出格式：
{{
  "action": "CLICK_ELEMENT",
  "selector": ".chapter-list a:first-child",
  "description": "点击第一章链接"
}}

或者：
{{
  "action": "EXTRACT_CONTENT",
  "content_type": "chapter_content",
  "description": "提取当前章节内容"
}}

网页内容（部分）：
{html[:15000]}
"""
        
        response = self._call_api(prompt)
        return response

    def parse_novel_homepage(self, html):
        """分析小说首页并提取信息"""
        prompt = f"""你是一个网页分析专家。请分析以下小说网站的HTML内容，提取小说的基本信息：
1. 小说标题
2. 作者
3. 描述/简介
4. 第一章的链接元素（提供CSS选择器，以便程序能定位到该元素）

你必须以JSON格式返回上述信息，格式如下：
{{
  "title": "小说标题",
  "author": "作者名",
  "description": "小说简介...",
  "first_chapter_selector": ".chapter-list a:first-child"
}}

HTML内容：
{html[:15000]}
"""
        
        response = self._call_api(prompt)
        novel_info = self._parse_json_response(response)
        
        if not novel_info:
            return {"title": None, "author": None, "description": None, "first_chapter_selector": None}
        
        return novel_info
    
    def extract_chapter_links(self, html):
        """分析页面并提取所有章节链接"""
        prompt = f"""你是一个网页分析专家。请分析以下小说网站的HTML内容，提取所有章节链接信息：
1. 所有章节的标题和链接（必须返回所有章节，不要遗漏任何章节）
2. 展开全部章节的按钮选择器（如果存在）

你必须以JSON格式返回上述信息，格式如下：
{{
  "expand_button_selector": ".show-all-chapters",
  "chapters": [
    {{"title": "第1章 xxx", "selector": ".chapter-list a:nth-child(1)"}},
    {{"title": "第2章 yyy", "selector": ".chapter-list a:nth-child(2)"}},
    ...
  ]
}}

重要提示：
1. 必须返回所有章节，不要遗漏任何章节
2. 如果章节列表很长，请确保返回完整的列表
3. 如果没有找到展开按钮，请将expand_button_selector设置为null
4. 请仔细检查HTML内容，确保没有遗漏任何章节

HTML内容：
{html[:15000]}
"""
        
        response = self._call_api(prompt)
        chapter_data = self._parse_json_response(response)
        
        if not chapter_data:
            return {"expand_button_selector": None, "chapters": []}
        
        return chapter_data
    
    def analyze_chapter_page(self, html):
        """分析章节页面并提取内容"""
        prompt = f"""你是一个网页分析专家。请分析以下小说章节页面的HTML内容，并执行以下任务：
1. 提取章节标题
2. 提取章节的正文内容（纯文本，不包含广告等）
3. 找到"下一章"链接的选择器

你必须以JSON格式返回上述信息，格式如下：
{{
  "title": "章节标题",
  "content": "章节正文内容...",
  "next_chapter_selector": ".next-chapter"
}}

如果未找到下一章链接，请将next_chapter_selector设置为null。

HTML内容：
{html[:20000]}
"""
        
        response = self._call_api(prompt)
        chapter_data = self._parse_json_response(response)
        
        if not chapter_data:
            return {"title": None, "content": None, "next_chapter_selector": None}
        
        return chapter_data
    
    def categorize_novel(self, title, description, first_chapter_content=None):
        """根据小说信息分类"""
        content = f"小说标题：{title}\n小说描述：{description}"
        if first_chapter_content:
            content += f"\n首章内容片段：{first_chapter_content[:1000]}..."
        
        prompt = f"""请根据以下小说信息，从以下类型中选择最合适的一个：
1. 武侠修真
2. 都市言情
3. 历史军事
4. 科幻灵异
5. 游戏竞技
6. 二次元
7. 玄幻奇幻
8. 其他

以下是小说信息：
{content}

请以JSON格式返回，格式为：{{"category_id": 数字, "category_name": "类型名称"}}
"""
        
        response = self._call_api(prompt)
        category_data = self._parse_json_response(response)
        
        if not category_data:
            return {"category_id": 8, "category_name": "其他"}
        
        return category_data

    def all_in_one_analysis(self, html, state=None):
        """一体化分析：解析HTML、提取内容并决定下一步操作"""
        
        # 不优化HTML，直接使用完整内容
        optimized_html = self._optimize_html(html)
        
        # 记录HTML大小
        html_size = len(optimized_html)
        print(f"\n[DeepSeek] [分析] HTML大小: {html_size} 字符")
        
        state_info = ""
        if state:
            state_info = f"""
当前爬虫状态：
{json.dumps(state, ensure_ascii=False, indent=2)}
"""
        
        # 构建提示词，根据模型类型提供不同的指令
        if self.model == 'deepseek-chat':
            # Chat模型
            prompt = f"""你是一个网页分析专家。请分析以下小说网站的HTML内容，提取所有章节链接信息。

请完成以下任务：
1. 确定页面类型（章节列表页或章节内容页）
2. 提取小说基本信息（标题、作者、简介）
3. 找出所有章节的标题和链接URL (网址格式为：/look/数字/数字.html)

重要说明：HTML中已经包含了全部章节信息（可能有200多章），无需考虑隐藏内容或额外点击"展开全部"按钮。请确保提取所有可见章节。

你可以用以下两种方式之一返回分析结果：

方式一：JSON格式
```json
{{
  "page_type": "chapter_list",
  "title": "小说标题",
  "author": "作者名",
  "description": "小说简介",
  "chapters": [
    {{"title": "章节标题", "url": "/look/12345/1.html"}},
    {{"title": "章节标题", "url": "/look/12345/2.html"}},
    ...
  ]
}}
```

方式二：简单列表格式（每行一个章节）
```
小说标题：xxx
作者：xxx
简介：xxx

章节列表：
章节标题1 - /look/12345/1.html
章节标题2 - /look/12345/2.html
...
```

重要提示：
1. 必须提取所有章节，不要遗漏任何章节
2. 如果章节列表很长（可能有200多章），请确保返回完整的列表
3. 所有章节的信息已在HTML中，无需假设有章节被隐藏
4. 请注意查找所有包含"/look/"路径的链接作为章节URL

HTML内容第一部分：
{optimized_html[:80000]}

HTML内容第二部分：
{optimized_html[80000:150000]}
"""
        else:
            # Reasoner模型
            prompt = f"""请分析以下小说网站HTML内容并提取所有信息。你是一位网页分析专家，需要从这个HTML源码中提取尽可能多的章节信息。

重要说明：HTML中已经包含了全部章节信息（可能有200多章），无需考虑隐藏内容或额外点击"展开全部"按钮。请确保提取所有可见章节。

分析步骤：
1. 判断页面类型：这是包含章节列表的目录页还是单章节内容页？
2. 提取小说基本信息：
   - 标题：通常在h1或h2标签中
   - 作者：查找包含"作者"关键词的文本
   - 简介：提取小说介绍文本
3. 提取所有章节信息：
   - 章节标题
   - 章节URL (形如 /look/数字/数字.html)
   - 注意：必须提取所有章节，请检查所有href属性包含"/look/"的链接

输出要求：
1. 先提供小说标题、作者和简介
2. 然后列出所有发现的章节，格式为"章节标题 - URL"
3. 确保提取全部章节（可能有200多章）

{state_info}

HTML内容第一部分：
{optimized_html[:80000]}

HTML内容第二部分：
{optimized_html[80000:150000]}
"""
        
        start_time = time.time()
        print(f"[DeepSeek] [分析] 开始调用API分析页面...")
        
        try:
            # 调用API获取分析结果
            result = self._call_api(prompt)
            
            if not result:
                print("[DeepSeek] [分析] 完整分析失败，返回默认结果")
                return {
                    "page_type": "unknown",
                    "next_action": {
                        "type": "GO_BACK",
                        "description": "分析失败，建议返回上一页"
                    }
                }
            
            # 计算耗时
            total_time = time.time() - start_time
            
            # 如果返回的是原始响应
            if "raw_response" in result:
                print(f"[DeepSeek] [分析] JSON解析失败，返回原始响应")
                return result
            
            # 输出分析结果
            page_type = result.get("page_type", "unknown")
            next_action = result.get("next_action", {}).get("type", "未知")
            
            print(f"[DeepSeek] [分析] 结果: 页面类型={page_type}, 下一步操作={next_action}")
            print(f"[DeepSeek] [分析] 总耗时: {total_time:.2f}秒")
            
            # 如果是章节内容页，记录内容信息
            if page_type == "chapter_content" and "chapter_data" in result:
                content_size = len(result["chapter_data"].get("content", ""))
                print(f"[DeepSeek] [分析] 提取内容大小: {content_size} 字符")
                
                has_translation = bool(result["chapter_data"].get("content_en"))
                has_summary = bool(result["chapter_data"].get("summary"))
                print(f"[DeepSeek] [分析] 包含翻译: {'是' if has_translation else '否'}")
                print(f"[DeepSeek] [分析] 包含摘要: {'是' if has_summary else '否'}")
            
            # 如果是章节列表页，输出章节数量
            if page_type == "chapter_list" and "chapters" in result:
                chapters = result.get("chapters", [])
                print(f"[DeepSeek] [分析] 提取章节数量: {len(chapters)}")
            
            return result
            
        except Exception as e:
            print(f"[DeepSeek] [分析] 发生异常: {str(e)}")
            print(f"[DeepSeek] [分析] 异常详情: {traceback.format_exc()}")
            
            return {
                "page_type": "unknown",
                "next_action": {
                    "type": "GO_BACK",
                    "description": "发生错误，建议返回上一页"
                }
            }

    def batch_translate(self, texts, batch_size=5):
        """批量翻译多个文本，以减少Deepseek调用次数"""
        if not texts:
            return []
            
        print(f"[DeepSeek] [批量] 开始处理 {len(texts)} 个文本，批次大小: {batch_size}")
        
        results = []
        batches = [texts[i:i+batch_size] for i in range(0, len(texts), batch_size)]
        
        for i, batch in enumerate(batches):
            print(f"[DeepSeek] [批量] 处理批次 {i+1}/{len(batches)}")
            
            # 构建批处理提示
            batch_prompt = "请将以下多个中文文本翻译成英文，按原始顺序返回翻译结果，使用JSON格式：\n\n"
            for j, text in enumerate(batch):
                batch_prompt += f"文本{j+1}:\n{text[:2000]}...\n\n"
                
            batch_prompt += "返回格式：\n{\n  \"translations\": [\n    \"英文翻译1\",\n    \"英文翻译2\",\n    ...\n  ]\n}"
            
            # 调用API
            response = self._call_api(batch_prompt)
            batch_results = self._parse_json_response(response)
            
            if batch_results and "translations" in batch_results:
                results.extend(batch_results["translations"])
            else:
                # 如果批处理失败，退回到逐个处理
                print("[DeepSeek] [批量] 批处理失败，退回到逐个处理")
                for text in batch:
                    result = self.translate_to_english(text)
                    results.append(result)
                    
        print(f"[DeepSeek] [批量] 完成，处理了 {len(results)} 个文本")
        return results 

    def analyze_structured_data(self, structured_data, chapters_count):
        """分析预先提取的结构化章节数据"""
        if not structured_data:
            ai_logger.warning("⚠️ 结构化数据为空，无法分析")
            return None
            
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
            ai_logger.info(f"🔍 检测到完整章节列表 ({len(chapters)}章)，直接处理")
            
            # 构建标准化格式的结果
            result = ""
            for chapter in chapters:
                result += f"<<<CHAPTER_START>>>\n"
                result += f"标题：{chapter['title']}\n"
                result += f"链接：{chapter['url']}\n"
                result += f"<<<CHAPTER_END>>>\n\n"
            
            result += "<<<PROCESSING_COMPLETE>>>\n"
            ai_logger.info(f"✅ 直接格式化处理完成，已生成标准协议格式")
            
            return result
        
        # 否则，调用大模型处理预览章节
        ai_logger.info(f"🤖 章节列表不完整 (仅有{len(chapters)}章，目标{chapters_count}章)，调用大模型处理")
        
        prompt = f"""分析以下从网页预提取的小说章节信息，生成规范化的章节目录。

提取的内容：
{structured_data}

任务说明：
1. 分析现有章节标题，找出命名规律并规范化标题格式
2. 返回完整的章节列表（总计{chapters_count}章）
3. 保持章节的正确顺序

请按以下格式输出每章信息：
<<<CHAPTER_START>>>
标题：章节标题
链接：章节URL
<<<CHAPTER_END>>>

只需要输出章节信息，不要添加其他说明或评论。
"""
        
        ai_logger.info(f"🚀 发送章节处理请求给DeepSeek API")
        response = self._call_api(prompt)
        if isinstance(response, dict) and "raw_response" in response:
            ai_logger.warning("⚠️ API返回字典类型结果，提取raw_response")
            return response["raw_response"]
            
        ai_logger.info(f"✅ 章节处理完成，响应长度: {len(response) if response else 0} 字符")
        return response
    
    def parse_chapters_from_response(self, response):
        """从模型响应中提取章节信息"""
        if not response:
            return []
            
        chapters = []
        
        # 尝试解析基于标记的结构
        pattern = r"<<<CHAPTER_START>>>(.*?)<<<CHAPTER_END>>>"
        matches = re.findall(pattern, response, re.DOTALL)
        
        if matches:
            for match in matches:
                title_match = re.search(r"标题[:：]\s*(.*?)(?:\n|$)", match)
                url_match = re.search(r"链接[:：]\s*(.*?)(?:\n|$)", match)
                
                if title_match and url_match:
                    title = title_match.group(1).strip()
                    url = url_match.group(1).strip()
                    
                    # 清理标题并添加章节
                    if title and url:
                        chapters.append({
                            "title": title, 
                            "url": url
                        })
        else:
            # 尝试解析简单的"标题 - URL"格式
            pattern = r"([^-\n]+)\s*-\s*(/\S+\.html)"
            matches = re.findall(pattern, response)
            
            for title, url in matches:
                if title.strip() and url.strip():
                    chapters.append({
                        "title": title.strip(),
                        "url": url.strip()
                    })
        
        ai_logger.info(f"从DeepSeek响应中解析出 {len(chapters)} 个章节")
        return chapters 