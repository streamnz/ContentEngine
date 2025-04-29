import json
import time
import datetime
import re
import traceback
from openai import OpenAI
from config import DEEPSEEK_CONFIG
import logging

logger = logging.getLogger(__name__)

class DeepSeekClient:
    def __init__(self):
        self.client = OpenAI(
            api_key=DEEPSEEK_CONFIG['api_key'],
            base_url=DEEPSEEK_CONFIG['base_url']
        )
        self.model = DEEPSEEK_CONFIG['model']
        # 用于统计API调用
        self.api_calls_count = 0
        self.total_time_spent = 0
        
        # 增加缓存功能
        self.cache = {}
        self.cache_hits = 0
        
        # HTML压缩选项
        self.compress_html = True
        self.html_target_size = 200000  # 目标HTML大小，单位字节

    def _optimize_html(self, html):
        """压缩和优化HTML以减少API调用大小"""
        if not self.compress_html:
            return html[:30000]  # 仍然截断，但不做其他处理
            
        # 计算原始大小
        original_size = len(html)
        
        if original_size <= self.html_target_size:
            return html  # 已经够小，不需要压缩
            
        import re
        
        # 1. 移除所有脚本标签
        html = re.sub(r'<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>', '', html)
        
        # 2. 移除所有样式标签
        html = re.sub(r'<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>', '', html)
        
        # 3. 移除所有注释
        html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
        
        # 4. 移除所有空格、换行符和制表符
        html = re.sub(r'[\n\t]+', ' ', html)
        html = re.sub(r'\s{2,}', ' ', html)
        
        # 5. 移除所有图片标签
        html = re.sub(r'<img\b[^>]*>', '', html)
        
        # 6. 移除所有空的div和span标签
        html = re.sub(r'<(div|span)[^>]*>\s*<\/\1>', '', html)
        
        # 7. 移除所有链接属性（除了href）
        html = re.sub(r'<a\b([^>]*?href="[^"]*"[^>]*?)>', lambda m: re.sub(r'\s+\w+="[^"]*"', '', m.group(0)), html)
        
        # 8. 移除所有meta标签
        html = re.sub(r'<meta\b[^>]*>', '', html)
        
        # 9. 移除所有iframe标签
        html = re.sub(r'<iframe\b[^>]*>.*?<\/iframe>', '', html, flags=re.DOTALL)
        
        # 10. 移除所有noscript标签
        html = re.sub(r'<noscript\b[^>]*>.*?<\/noscript>', '', html, flags=re.DOTALL)
        
        # 11. 移除所有事件处理属性
        html = re.sub(r'\s+on\w+="[^"]*"', '', html)
        
        # 12. 移除所有data-*属性
        html = re.sub(r'\s+data-\w+="[^"]*"', '', html)
        
        # 13. 移除所有class属性
        html = re.sub(r'\s+class="[^"]*"', '', html)
        
        # 14. 移除所有id属性
        html = re.sub(r'\s+id="[^"]*"', '', html)
        
        # 15. 移除所有style属性
        html = re.sub(r'\s+style="[^"]*"', '', html)
        
        # 16. 移除所有隐藏的SVG定义和符号
        html = re.sub(r'<div\s+hidden[^>]*>.*?<\/div>', '', html, flags=re.DOTALL)
        html = re.sub(r'<svg[^>]*>.*?<\/svg>', '', html, flags=re.DOTALL)
        html = re.sub(r'<defs>.*?<\/defs>', '', html, flags=re.DOTALL)
        html = re.sub(r'<symbol[^>]*>.*?<\/symbol>', '', html, flags=re.DOTALL)
        
        # 检查优化后的大小
        optimized_size = len(html)
        compression_ratio = (original_size - optimized_size) / original_size * 100
        
        print(f"[DeepSeek] [优化] HTML原始大小: {original_size} 字节, 优化后: {optimized_size} 字节, 压缩率: {compression_ratio:.2f}%")
        
            
        return html

    def _call_api(self, prompt, use_cache=False):
        """通用API调用方法，带缓存功能"""
        # 检查缓存
        if use_cache and prompt in self.cache:
            self.cache_hits += 1
            hit_rate = (self.cache_hits / (self.api_calls_count + self.cache_hits)) * 100
            logger.info(f"缓存命中! 总命中率: {hit_rate:.2f}%")
            return self.cache[prompt]
            
        self.api_calls_count += 1
        current_call = self.api_calls_count
        
        # 记录开始时间
        start_time = time.time()
        start_datetime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        logger.info(f"API调用 #{current_call} 开始时间: {start_datetime}")
        logger.info(f"API调用 #{current_call} 提示词长度: {len(prompt)} 字符")
        
        try:
            # 构建请求数据
            request_data = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 8192,  # 修改为API允许的最大值
                "stream": False,
                "top_p": 0.95,
                "frequency_penalty": 0.3,
                "presence_penalty": 0.3,
                "response_format": {"type": "json_object"}  # 启用JSON Output
            }
            
            # 发送请求
            response = self.client.chat.completions.create(**request_data)
            
            # 计算耗时
            total_time = time.time() - start_time
            self.total_time_spent += total_time
            
            if response.choices and len(response.choices) > 0:
                result = response.choices[0].message.content
                
                if not result or len(result.strip()) == 0:
                    logger.error(f"API调用 #{current_call} 响应内容为空")
                    return None
                
                # 尝试解析JSON响应
                try:
                    result_json = json.loads(result)
                    logger.info(f"API调用 #{current_call} 响应长度: {len(result)} 字符")
                    logger.info(f"API调用 #{current_call} 状态: 成功")
                    logger.info(f"API调用 #{current_call} 耗时: {total_time:.2f}秒")
                    
                    # 缓存结果
                    if use_cache:
                        self.cache[prompt] = result_json
                    
                    return result_json
                except json.JSONDecodeError:
                    logger.error(f"API调用 #{current_call} JSON解析失败")
                    return None
            else:
                logger.error(f"API调用 #{current_call} 错误: 响应中没有choices字段")
                return None
                
        except Exception as e:
            logger.error(f"API调用 #{current_call} 发生异常")
            logger.error(f"异常信息: {str(e)}")
            logger.error(f"异常详情: {traceback.format_exc()}")
            return None

    def _parse_json_response(self, response):
        """解析API返回的JSON，支持各种格式"""
        if not response:
            logger.error("[解析] 响应为空")
            return None
            
        logger.info(f"[解析] 尝试解析响应，长度: {len(response)} 字符")
        
        try:
            # 1. 如果有Markdown代码块，提取其中的JSON
            if "```json" in response:
                parts = response.split("```json")
                if len(parts) > 1:
                    json_part = parts[1].split("```")[0].strip()
                    try:
                        result = json.loads(json_part)
                        logger.info(f"[解析] 成功从代码块解析JSON")
                        return result
                    except:
                        pass
            
            # 2. 尝试直接解析整个响应
            try:
                result = json.loads(response)
                logger.info(f"[解析] 成功直接解析JSON")
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
                    logger.info(f"[解析] 成功从文本中提取JSON")
                    return result
                except:
                    pass
            
            # 4. 如果都失败了，尝试从文本中提取关键信息
            logger.warning("[解析] 无法解析JSON，尝试从文本提取信息")
            
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
            logger.error(f"[解析] 发生异常: {str(e)}")
            logger.error(f"[解析] 异常详情: {traceback.format_exc()}")
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
1. 所有章节的标题和链接
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

如果没有找到展开按钮，请将expand_button_selector设置为null。

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
        
        # 优化HTML以减少API调用大小
        optimized_html = self._optimize_html(html)
        
        # 记录优化后的HTML大小
        html_size = len(optimized_html)
        print(f"\n[DeepSeek] [分析] 优化后HTML大小: {html_size} 字节")
        
        state_info = ""
        if state:
            state_info = f"""
当前爬虫状态：
{json.dumps(state, ensure_ascii=False, indent=2)}
"""
        
        # 构建更结构化的提示词
        prompt = f"""作为网页分析专家，请分析以下HTML内容并以JSON格式返回分析结果。要求：精确、可靠、保持一致性。

任务要求：
1. 页面类型判断（必选其一）：
   - chapter_list：包含多个章节链接的页面（如目录页）
   - chapter_content：包含单章节正文的页面

2. 信息提取（根据页面类型）：
   A. 章节列表页：
      - 小说标题：优先从h1、h2标签提取
      - 作者名：查找包含"作者"关键词的相邻文本
      - 小说简介：从介绍/简介区块提取
      - 章节列表：提取所有章节链接和标题
   
   B. 章节内容页：
      - 章节标题：从h1、h2标签提取
      - 正文内容：定位主要内容区块，必须包含完整的章节内容
      - 内容处理：
        * 清理广告、导航等无关内容
        * 生成100字以内的摘要
        * 翻译成英文（保持文学性）

3. 下一步指示：
   - chapter_list页面：提供首章链接选择器
   - chapter_content页面：提供下一章链接或URL

请以JSON格式返回，格式如下：
{{
  "page_type": "chapter_list|chapter_content",
  "title": "小说标题",
  "author": "作者名",
  "description": "小说简介",
  "chapters": [
    {{"title": "章节标题", "url": "章节URL"}}
  ],
  "chapter_data": {{  // 仅章节内容页包含
    "title": "章节标题",
    "content": "清理后的正文",
    "content_en": "英文翻译",
    "summary": "内容摘要"
  }},
  "next_action": {{
    "type": "CLICK_ELEMENT|NEXT_CHAPTER",
    "selector": "CSS选择器或URL",
    "description": "操作说明"
  }}
}}

HTML内容：
{optimized_html}
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
            
            # 输出分析结果
            page_type = result.get("page_type", "unknown")
            next_action = result.get("next_action", {}).get("type", "未知")
            
            print(f"[DeepSeek] [分析] 结果: 页面类型={page_type}, 下一步操作={next_action}")
            print(f"[DeepSeek] [分析] 总耗时: {total_time:.2f}秒")
            
            # 如果是章节内容页，记录内容信息
            if page_type == "chapter_content" and "chapter_data" in result:
                content_size = len(result["chapter_data"].get("content", ""))
                print(f"[DeepSeek] [分析] 提取内容大小: {content_size} 字节")
                
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
        """批量翻译多个文本，以减少API调用次数"""
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