import os
import json
import asyncio
import traceback
import time
import datetime
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from playwright.async_api import async_playwright
from database.database import Database
from ai_client.deepseek_client import DeepSeekClient
from ai_client.claude_client import ClaudeClient
from config import CRAWLER_CONFIG, PROMPT_TEMPLATES, STORAGE_CONFIG, COOKIES
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

# 配置日志
def setup_logging():
    """配置日志系统"""
    # 创建日志目录
    os.makedirs('logs', exist_ok=True)
    
    # 配置日志格式
    log_format = '%(asctime)s [%(levelname)s] [%(name)s] %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    
    # 文件处理器
    file_handler = logging.FileHandler(
        f'logs/crawler_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.log',
        encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter(log_format, date_format))
    
    # 控制台处理器 - 带有颜色
    class ColoredFormatter(logging.Formatter):
        """为不同级别的日志添加颜色"""
        COLORS = {
            'DEBUG': '\033[36m',    # 青色
            'INFO': '\033[32m',     # 绿色
            'WARNING': '\033[33m',  # 黄色
            'ERROR': '\033[31m',    # 红色
            'CRITICAL': '\033[41m',  # 红底
            'RESET': '\033[0m'      # 重置
        }
        
        def format(self, record):
            log_message = super().format(record)
            color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
            return f"{color}{log_message}{self.COLORS['RESET']}"
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(ColoredFormatter(log_format, date_format))
    
    # 配置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # 创建爬虫专用logger
    crawler_logger = logging.getLogger('crawler')
    crawler_logger.setLevel(logging.INFO)
    
    # 创建网络请求专用logger
    network_logger = logging.getLogger('network')
    network_logger.setLevel(logging.INFO)
    
    # 创建解析专用logger
    parser_logger = logging.getLogger('parser')
    parser_logger.setLevel(logging.INFO)
    
    # 创建数据库专用logger
    db_logger = logging.getLogger('database')
    db_logger.setLevel(logging.INFO)
    
    # 创建AI/大模型专用logger
    ai_logger = logging.getLogger('ai')
    ai_logger.setLevel(logging.INFO)
    
    return crawler_logger

# 创建专用loggers
logger = setup_logging()
network_logger = logging.getLogger('network')
parser_logger = logging.getLogger('parser')
db_logger = logging.getLogger('database')
ai_logger = logging.getLogger('ai')

class NovelCrawler:
    def __init__(self):
        self.db = Database()
        self.deepseek_client = DeepSeekClient()
        self.claude_client = ClaudeClient()  # 添加Claude客户端
        self.base_url = CRAWLER_CONFIG['base_url']
        self.headers = CRAWLER_CONFIG['headers']
        self.lock = asyncio.Lock()  # 添加asyncio锁对象，用于同步页面访问
        self.state = {
            "phase": "initial",  # initial, novel_info, chapter_list, chapter_content
            "novel_id": None,
            "novel_title": None,
            "author": None,
            "current_chapter": 0,
            "completed_chapters": [],
            "chapters": [],  # 保存所有章节信息
            "current_url": None
        }
        self.browser_initialized = False
        
        # 性能调优参数
        self.parallel_chapters = 3  # 并行爬取章节数
        self.wait_timeout = 5000  # 元素等待超时时间(ms)
        self.page_timeout = 30000  # 页面加载超时时间(ms)
        self.enable_js_blocking = True  # 是否阻止非必要JS加载
        self.skip_images = True  # 是否跳过图片加载
        
        logger.info("爬虫初始化完成")

    async def init_browser(self):
        """初始化浏览器，使用 Firefox 内核"""
        try:
            logger.info("开始初始化浏览器（Firefox内核）")
            self.playwright = await async_playwright().start()
            context_options = {
                'viewport': {'width': 1280, 'height': 800},
                'ignore_https_errors': True,
                'java_script_enabled': True,
                'bypass_csp': True,
            }
            # 使用 Firefox 浏览器
            self.browser = await self.playwright.firefox.launch_persistent_context(
                os.path.abspath("./firefox-profile-playwright"),
                headless=False,
                **context_options
            )
            self.context = self.browser
            # 使用已有页面，不创建新的空白标签页
            pages = self.context.pages
            self.page = pages[0] if pages else await self.context.new_page()
            logger.info("浏览器初始化成功（Firefox内核）")
        except Exception as e:
            logger.error(f"浏览器初始化失败: {e}")
            logger.error(traceback.format_exc())
            await self.close_browser()
            raise e

    async def close_browser(self):
        """关闭浏览器"""
        try:
            if hasattr(self, 'browser') and self.browser:
                await self.browser.close()
            if hasattr(self, 'playwright') and self.playwright:
                await self.playwright.stop()
            self.browser_initialized = False
            logger.info("浏览器已关闭")
        except Exception as e:
            logger.error(f"关闭浏览器出错: {e}")

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
            r'_.*? - 笔趣阁'
        ]
        
        for pattern in patterns_to_remove:
            cleaned_title = re.sub(pattern, '', cleaned_title)
        
        # 处理特定网站的标题格式
        if ' - 笔趣阁' in cleaned_title:
            cleaned_title = cleaned_title.replace(' - 笔趣阁', '')
        
        # 去除多余空格并整理格式
        cleaned_title = re.sub(r'\s+', ' ', cleaned_title).strip()
        return cleaned_title
    
    def get_clean_chapter_name(self, chapter_title, chapter_index):
        """获取干净的章节名称，去除重复的章节序号"""
        if not chapter_title:
            return f"第{chapter_index+1}章"
            
        # 先清理标题
        title = self.clean_chapter_title(chapter_title)
        
        # 提取章节名称，去除章节号和小说名
        # 示例：'星门-第1章 巡检司-笔趣阁' -> '巡检司'
        name_parts = []
        
        # 按分隔符分割标题
        for part in re.split(r'[-_\s]', title):
            # 跳过空部分
            if not part.strip():
                continue
                
            # 跳过章节编号
            if re.search(r'^第?\d+章', part):
                continue
                
            # 跳过网站名称
            if re.search(r'笔趣阁|小说网|阅读网', part):
                continue
                
            # 跳过小说名称
            if part.strip() == self.state["novel_title"]:
                continue
                
            # 添加有效部分
            name_parts.append(part.strip())
        
        # 如果提取到了章节名
        if name_parts:
            return ' '.join(name_parts)
            
        # 尝试直接从标题提取实际章节名
        chapter_name_match = re.search(r'第\d+章\s*(.+?)(?:-|_|\s*-\s*笔趣阁|$)', title)
        if chapter_name_match:
            return chapter_name_match.group(1).strip()
        
        # 如果上述方法都失败，回退到使用默认命名
        return f"第{chapter_index+1}章"

    def clean_chapter_content(self, content):
        """清理章节内容，去除广告、导航等信息"""
        if not content:
            return ""
            
        # 分行处理
        lines = content.split('\n')
        cleaned_lines = []
        
        # 要过滤的广告和导航信息模式
        ad_patterns = [
            r'新书推荐：.*',
            r'温馨提示：.*',
            r'加入书签：.*',
            r'收藏本站：.*',
            r'上一章.*下一章.*',
            r'点此报错.*',
            r'手机阅读.*',
            r'章节错误.*',
            r'https?://.*',
            r'笔趣阁.*',
            r'本章未完.*',
            r'.*最新章节.*',
            r'.*更新时间.*',
            r'.*小说网.*',
            r'.*阅读地址.*',
            r'.*txt下载.*',
            r'喜欢.*请大家收藏.*',
            r'[（\(].*?www.*?[）\)]',
            r'『加入书签』',
            r'『推荐票』',
            r'『打赏』',
            r'『投月票』',
            r'PS[:：].*',
            r'ps[:：].*',
            r'作者有话说[:：].*',
            r'作者说[:：].*',
            r'.*求支持.*',
            r'.*求订阅.*',
            r'.*求月票.*',
            r'.*求推荐票.*',
            r'^\s*$'  # 空行
        ]
        
        # 新增：过滤作者留言相关段落的标志
        in_author_note = False
        
        # 过滤每一行
        for line in lines:
            # 检查是否开始作者留言段落
            if re.search(r'PS[：:](.*?)', line, re.IGNORECASE) or \
               re.search(r'作者有话说[：:](.*?)', line, re.IGNORECASE) or \
               re.search(r'求.*支持', line, re.IGNORECASE) or \
               re.search(r'新书.*?求', line, re.IGNORECASE):
                in_author_note = True
                continue
                
            # 检查是否为结束标记
            if re.search(r'『.*?』', line) or re.search(r'---+', line):
                in_author_note = False
                continue
            
            # 如果在作者留言段落中，跳过此行
            if in_author_note:
                continue
            
            should_keep = True
            for pattern in ad_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    should_keep = False
                    break
            
            # 行太短可能是章节分隔符或广告
            if len(line.strip()) < 5:
                should_keep = False
                
            if should_keep:
                cleaned_lines.append(line)
        
        # 重新组合内容并清理首尾空白
        cleaned_content = '\n'.join(cleaned_lines).strip()
        
        # 多次迭代清理空行
        while '\n\n\n' in cleaned_content:
            cleaned_content = cleaned_content.replace('\n\n\n', '\n\n')
            
        # 移除最后一段如果疑似作者留言
        paragraphs = cleaned_content.split('\n\n')
        if len(paragraphs) > 1:
            last_para = paragraphs[-1].lower()
            if ('ps' in last_para or '作者' in last_para or '求' in last_para or 
                '新书' in last_para or '谢谢' in last_para or '感谢' in last_para):
                cleaned_content = '\n\n'.join(paragraphs[:-1])
        
        return cleaned_content

    def save_to_file(self, novel_title, chapter_index, chapter_title, content):
        """保存章节内容到本地文件"""
        # 确保小说标题存在
        if not novel_title:
            novel_title = "未知小说"
            
        novel_dir = os.path.join(STORAGE_CONFIG['base_path'], novel_title)
        os.makedirs(novel_dir, exist_ok=True)
        
        # 获取干净的章节名称
        clean_name = self.get_clean_chapter_name(chapter_title, chapter_index)
        
        # 清理章节内容
        cleaned_content = self.clean_chapter_content(content) if content else ""
        
        # 如果内容为空，添加提示信息
        if not cleaned_content:
            cleaned_content = f"# 注意：此章节内容未能成功获取\n\n章节标题：{chapter_title}\n章节索引：{chapter_index + 1}\n\n可以稍后重试获取此章节内容，或前往原网站阅读。"
            logger.warning(f"章节 #{chapter_index+1} 内容为空，已添加提示信息")
        
        # 按照指定格式生成文件名：小说名称-章节序号-章节名称
        filename = f"{novel_title}-第{chapter_index+1}章-{clean_name}.txt"
        
        # 移除文件名中的非法字符
        filename = "".join(c for c in filename if c.isalnum() or c in "._- ")
        filepath = os.path.join(novel_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(cleaned_content)
        
        logger.info(f"已保存章节 #{chapter_index+1}: {filepath}")
        return filepath

    async def handle_js_requests(self, route):
        """处理JavaScript请求"""
        try:
            # 继续原始请求
            await route.continue_()
        except Exception as e:
            # 如果有错误，提供一个空的JS响应
            network_logger.warning(f"处理JS请求时出错: {e}")
            await route.fulfill(
                status=200,
                content_type="application/javascript",
                body="// 空JavaScript文件"
            )

    async def check_and_restart_browser(self):
        """检查浏览器状态，如果已关闭则重新启动"""
        if not self.browser_initialized or not self.browser or self.browser.is_connected() == False:
            print("[爬虫] 浏览器已关闭或未初始化，正在重新启动...")
            await self.close_browser()  # 确保资源被释放
            await self.init_browser()
            
            # 如果有当前URL，重新访问
            if self.state["current_url"]:
                try:
                    await self.page.goto(self.state["current_url"], timeout=60000)
                    await asyncio.sleep(3)
                except Exception as e:
                    print(f"[爬虫] 重新访问当前页面失败: {e}")

    async def scroll_to_bottom(self, page):
        """滚动到页面底部并确保内容完全加载"""
        try:
            # 获取初始内容长度
            initial_content = await page.content()
            initial_length = len(initial_content)
            network_logger.info(f"初始页面大小: {initial_length/1024:.2f} KB")
            
            # 先快速滚动到底部
            await page.evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
            await asyncio.sleep(1)  # 减少等待时间
            
            # 禁用可能出错的脚本
            await page.evaluate('''() => {
                // 阻止常见的错误
                window.book = window.book || {};
                window.dd_show = function() {};
                
                // 检查是否有"加载更多"按钮并点击
                const loadMoreButtons = Array.from(document.querySelectorAll('a, button, div')).filter(el => 
                    el.textContent && (
                        el.textContent.includes('加载') || 
                        el.textContent.includes('展开') || 
                        el.textContent.includes('更多')
                    )
                );
                loadMoreButtons.forEach(btn => btn.click());
                
                // 查找章节内容容器
                const contentElements = [
                    document.getElementById('content'),
                    document.querySelector('.article-content'),
                    document.querySelector('.chapter-content'),
                    document.querySelector('.content'),
                    ...Array.from(document.querySelectorAll('div')).filter(el => 
                        el.className && (
                            el.className.includes('content') || 
                            el.className.includes('article') || 
                            el.className.includes('chapter')
                        )
                    )
                ].filter(Boolean);
                
                // 尝试展开所有折叠内容
                contentElements.forEach(el => {
                    if(el.style) {
                        el.style.height = 'auto';
                        el.style.maxHeight = 'none';
                        el.style.overflow = 'visible';
                    }
                });
            }''')
            
            await asyncio.sleep(0.5)  # 减少等待时间
            
            # 再次滚动确保所有内容加载
            await page.evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
            await asyncio.sleep(0.5)  # 减少等待时间
            
            # 获取最终内容
            final_content = await page.content()
            final_length = len(final_content)
            network_logger.info(f"滚动后页面大小: {final_length/1024:.2f} KB (增加: {(final_length-initial_length)/1024:.2f} KB)")
            
            # 对某些特定的网站使用特殊处理
            await page.evaluate('''() => {
                // 阻止常见的错误
                window.book = window.book || {};
                window.dd_show = function() {};
                
                // 尝试执行网站特定的脚本解锁内容
                if (document.querySelector('.read-content')) {
                    // 部分网站通过js控制显示内容
                    document.querySelectorAll('.read-content')[0].style.height = 'auto';
                    document.querySelectorAll('.read-content')[0].style.overflow = 'visible';
                }
            }''')
            
            return final_content
            
        except Exception as e:
            logger.error(f"滚动页面时发生错误: {e}")
            return await page.content()  # 发生错误时返回当前内容

    async def extract_chapter_content_from_dom(self, html):
        """使用DOM预处理提取章节内容"""
        soup = BeautifulSoup(html, 'html.parser')
        result = {
            "title": "",
            "content": "",
            "is_complete": False
        }
        
        # 提取章节标题
        title_candidates = [
            soup.select_one('h1.chapter-title, h1.title'),
            soup.select_one('div.chapter-title, div.title'),
            soup.select_one('h1, h2')
        ]
        
        for candidate in title_candidates:
            if candidate:
                result["title"] = candidate.text.strip()
                parser_logger.info(f"找到章节标题: {result['title'][:30]}...")
                break
        
        # 提取正文内容
        content_candidates = [
            soup.select_one('div.content, div.article-content'),
            soup.select_one('div.chapter-content'),
            soup.select_one('div#content, div#chapter-content'),
            soup.select_one('div.read-content')
        ]
        
        for candidate in content_candidates:
            if candidate:
                # 清理内容
                content = candidate.get_text(separator='\n').strip()
                # 移除空行和多余空白
                content = re.sub(r'\n\s*\n', '\n\n', content)
                result["content"] = content
                parser_logger.info(f"提取到内容: {len(content)} 字符")
                break
        
        # 检查是否完整
        result["is_complete"] = bool(result["content"])
        if result["is_complete"]:
            parser_logger.info(f"DOM提取成功")
        else:
            parser_logger.warning(f"DOM提取未找到内容")
        
        return result

    async def fetch_chapter_content(self, chapter_url, chapter_index, chapter_info=None):
        """获取章节内容，优先使用DOM处理，失败时使用大模型，添加重试机制"""
        retry_count = 0
        max_retries = 3  # 最大重试次数
        
        while retry_count <= max_retries:
            try:
                # 如果是重试，增加一条日志
                if retry_count > 0:
                    logger.info(f"第 {retry_count} 次重试获取章节 #{chapter_index+1}: {chapter_url}")
                else:
                    logger.info(f"正在获取章节 #{chapter_index+1}: {chapter_url}")
                
                # 保存当前cookies
                cookies = await self.context.cookies()
                
                # 创建新页面进行导航，避免主页面被中断
                page = await self.context.new_page()
                try:
                    # 设置页面超时
                    page.set_default_navigation_timeout(180000)
                    
                    # 访问章节页面
                    await page.goto(chapter_url, timeout=180000)
                    
                    # 等待内容加载
                    await page.wait_for_load_state('networkidle', timeout=30000)
                    
                    # 获取页面内容
                    html = await page.content()
                    
                    # 1. 首先尝试DOM处理
                    parser_logger.info(f"尝试DOM提取章节 #{chapter_index+1}")
                    dom_result = await self.extract_chapter_content_from_dom(html)
                    
                    if dom_result["is_complete"]:
                        # DOM处理成功，直接返回结果
                        chapter_title = dom_result["title"]
                        chapter_content = dom_result["content"]
                        is_complete = True
                        
                        # 保存到数据库
                        if self.state["novel_id"]:
                            # 确保URL是完整的
                            full_chapter_url = chapter_url if chapter_url.startswith('http') else urljoin(self.base_url, chapter_url)
                            
                            chapter_data = {
                                "novel_id": self.state["novel_id"],
                                "chapter_index": chapter_index,
                                "title": chapter_title,
                                "content": chapter_content,
                                "url": full_chapter_url,
                                "is_complete": is_complete,
                                "word_count": len(chapter_content),
                                "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            }
                            
                            db_logger.info(f"保存章节 #{chapter_index+1} 到数据库")
                            self.db.save_chapter(chapter_data)
                            
                            # 如果指定了本地存储，保存到文件
                            if STORAGE_CONFIG.get('save_to_file', False):
                                file_path = self.save_to_file(
                                    self.state["novel_title"], 
                                    chapter_index,
                                    chapter_title,
                                    chapter_content
                                )
                                logger.info(f"章节已保存到文件: {file_path}")
                        
                        await page.close()
                        return chapter_title, chapter_content, is_complete
                    
                    # 2. DOM处理失败，使用大模型处理
                    ai_logger.info(f"DOM处理失败，使用AI处理章节 #{chapter_index+1}")
                    
                    if CRAWLER_CONFIG['use_claude']:
                        # 使用Claude处理
                        ai_logger.info(f"Claude处理中... (输入大小: {len(html[:150000])} 字符)")
                        prompt = PROMPT_TEMPLATES['chapter_content'].format(content=html[:150000])
                        response = self.claude_client.call_claude(prompt)
                        
                        if response and "<<<CONTENT_START>>>" in response:
                            # 解析Claude响应
                            title_match = re.search(r"标题[:：]\s*(.*?)(?:\n|$)", response)
                            content_match = re.search(r"正文[:：]\s*([\s\S]*?)(?=<<<CONTENT_END>>>)", response)
                            
                            chapter_title = title_match.group(1).strip() if title_match else f"第{chapter_index+1}章"
                            chapter_content = content_match.group(1).strip() if content_match else ""
                            is_complete = "<<<PROCESSING_COMPLETE>>>" in response
                            
                            ai_logger.info(f"Claude处理成功: 提取 {len(chapter_content)} 字符")
                        else:
                            ai_logger.error(f"Claude处理失败")
                            raise Exception("Claude处理失败，尝试重试或使用DeepSeek")
                    else:
                        # 使用DeepSeek处理
                        ai_logger.info(f"DeepSeek处理中... (输入大小: {len(html[:80000])} 字符)")
                        prompt = PROMPT_TEMPLATES['chapter_content'].format(content=html[:80000])
                        response = self.deepseek_client._call_api(prompt)
                        
                        if response and "<<<CONTENT_START>>>" in response:
                            # 解析DeepSeek响应
                            title_match = re.search(r"标题[:：]\s*(.*?)(?:\n|$)", response)
                            content_match = re.search(r"正文[:：]\s*([\s\S]*?)(?=<<<CONTENT_END>>>)", response)
                            
                            chapter_title = title_match.group(1).strip() if title_match else f"第{chapter_index+1}章"
                            chapter_content = content_match.group(1).strip() if content_match else ""
                            is_complete = "<<<PROCESSING_COMPLETE>>>" in response
                            
                            ai_logger.info(f"DeepSeek处理成功: 提取 {len(chapter_content)} 字符")
                        else:
                            ai_logger.error(f"DeepSeek处理失败")
                            raise Exception("DeepSeek处理失败，尝试重试")
                    
                    # 保存到数据库
                    if self.state["novel_id"]:
                        # 确保URL是完整的
                        full_chapter_url = chapter_url if chapter_url.startswith('http') else urljoin(self.base_url, chapter_url)
                        
                        chapter_data = {
                            "novel_id": self.state["novel_id"],
                            "chapter_index": chapter_index,
                            "title": chapter_title,
                            "content": chapter_content,
                            "url": full_chapter_url,
                            "is_complete": is_complete,
                            "word_count": len(chapter_content),
                            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        
                        db_logger.info(f"保存AI处理的章节 #{chapter_index+1} 到数据库")
                        self.db.save_chapter(chapter_data)
                        
                        # 如果指定了本地存储，保存到文件
                        if STORAGE_CONFIG.get('save_to_file', False):
                            file_path = self.save_to_file(
                                self.state["novel_title"], 
                                chapter_index,
                                chapter_title,
                                chapter_content
                            )
                            logger.info(f"章节已保存到文件: {file_path}")
                    
                    await page.close()
                    return chapter_title, chapter_content, is_complete
                    
                finally:
                    # 确保页面关闭
                    if page and not page.is_closed():
                        await page.close()
                        
            except Exception as e:
                retry_count += 1
                logger.error(f"获取章节 #{chapter_index+1} 出错: {e}")
                
                if retry_count <= max_retries:
                    wait_time = retry_count * 2  # 指数退避策略
                    logger.info(f"等待 {wait_time} 秒后进行第 {retry_count} 次重试...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"章节 #{chapter_index+1} 重试 {max_retries} 次后仍获取失败")
                    logger.error(traceback.format_exc())
                    
                    # 最后尝试获取章节信息的备用方案
                    try:
                        # 如果URL中包含章节号和标题信息，尝试提取
                        chapter_number_match = re.search(r'/(\d+)\.html', chapter_url)
                        if chapter_number_match:
                            chapter_number = chapter_number_match.group(1)
                            backup_title = f"第{chapter_number}章"
                            
                            # 返回空内容但有标题，以便文件创建
                            return backup_title, "", False
                    except:
                        pass
                    
                    return "", "", False
            finally:
                # 确保恢复cookies
                try:
                    await self.context.add_cookies(cookies)
                except:
                    pass

    async def determine_max_chapter(self, novel_id, base_url):
        """根据AI解析结果确定小说的最大章节数"""
        # 如果已经有AI解析的章节列表，直接使用其长度
        if hasattr(self, 'chapters') and self.chapters:
            max_chapters = len(self.chapters)
            logger.info(f"使用AI解析结果确定最大章节数: {max_chapters}")
            return max_chapters
        
        # 如果没有AI解析结果，使用配置的默认值
        default_max = CRAWLER_CONFIG.get('max_chapters', 1000)
        logger.warning(f"未找到AI解析结果，使用默认最大章节数: {default_max}")
        return default_max

    async def crawl_novel(self, url: str, limit_chapters: int = 0):
        try:
            # 初始化浏览器
            await self.init_browser()
            # 自动模式：程序自动跳转到目标页面
            logger.info(f"正在访问页面: {url}")
            await self.page.goto(url, timeout=180000)
            # 滚动到底部确保加载所有章节
            await self.scroll_to_bottom(self.page)
            # 获取页面内容
            html = await self.page.content()
            # 首先使用DOM预处理提取章节列表
            logger.info("使用DOM预处理提取章节信息...")
            extracted_data = await self.extract_data_from_dom(html, "chapter_list")
            
            # 获取基本信息
            title = extracted_data.get("title", "未知标题")
            author = extracted_data.get("author", "未知作者")
            description = extracted_data.get("description", "")
            dom_chapters = extracted_data.get("chapters", [])
            
            # 更新状态中的小说标题和作者
            self.state["novel_title"] = title
            self.state["author"] = author
            
            logger.info(f"提取到小说信息: {title} - {author}")
            
            dom_chapters_count = len(dom_chapters)
            logger.info(f"DOM预处理提取到 {dom_chapters_count} 个章节")
            
            if dom_chapters_count > 0:
                # 将提取的章节信息转换为文本形式
                chapter_text = "\n".join([f"{i+1}. {chapter.get('title', '')} - {chapter.get('url', '')}" 
                                      for i, chapter in enumerate(dom_chapters)])
                
                # 构建结构化数据给大模型
                structured_data = f"""网站标题: {title}
作者: {author}
简介: {description}

章节列表:
{chapter_text}
"""
                
                # 首先尝试使用DeepSeek处理
                logger.info("使用DeepSeek分析提取的章节信息...")
                deepseek_result = self.deepseek_client.analyze_structured_data(structured_data, dom_chapters_count)
                
                # 检查DeepSeek处理结果
                if deepseek_result and "<<<CHAPTER_START>>>" in deepseek_result:
                    # 解析章节信息
                    self.chapters = self.deepseek_client.parse_chapters_from_response(deepseek_result)
                    is_complete = "<<<PROCESSING_COMPLETE>>>" in deepseek_result
                    logger.info(f"DeepSeek成功处理 {len(self.chapters)} 个章节")
                else:
                    # DeepSeek处理失败，尝试使用Claude
                    logger.info("DeepSeek处理失败，尝试使用Claude作为备选...")
                    claude_result = self.claude_client.analyze_structured_data(structured_data, dom_chapters_count)
                    
                    if claude_result and "<<<CHAPTER_START>>>" in claude_result:
                        self.chapters = self.claude_client.parse_chapters_from_response(claude_result)
                        is_complete = "<<<PROCESSING_COMPLETE>>>" in claude_result
                        logger.info(f"Claude成功处理 {len(self.chapters)} 个章节")
                    else:
                        # 如果两个模型都处理失败，使用DOM预处理的结果
                        logger.warning("大模型处理失败，使用DOM预处理的结果")
                        self.chapters = dom_chapters
                        is_complete = False
            else:
                # DOM预处理失败，直接使用大模型分析HTML
                logger.warning("DOM预处理提取章节失败，直接使用大模型分析HTML...")
                
                # 先尝试DeepSeek
                result = self.deepseek_client.all_in_one_analysis(html, self.state)
                
                if not result or not result.get("chapters"):
                    # DeepSeek失败，尝试Claude
                    logger.info("DeepSeek分析失败，使用Claude作为备选...")
                    result = self.claude_client.analyze_chapter_list(html, url, self.state)
                
                # 提取结果
                title = result.get("title", "未知")
                author = result.get("author", "未知")
                self.chapters = result.get("chapters", [])
                is_complete = result.get("is_complete", False)
            
            # 更新小说信息到数据库
            if self.state["novel_id"]:
                self.db.update_novel(
                    novel_id=self.state["novel_id"],
                    data={
                        "title": title,
                        "author": author,
                        "description": description,
                        "chapter_count": len(self.chapters),
                        "status": "ongoing" if not is_complete else "completed",
                        "last_updated": datetime.datetime.now()
                    }
                )
                novel_id = self.state["novel_id"]
            else:
                novel_id = self.db.insert_novel(
                    title=title,
                    author=author,
                    description=description
                )
                self.state["novel_id"] = novel_id
            
            logger.info(f"已保存/更新小说信息，ID: {novel_id}")
            
            # 使用AI解析的章节列表
            logger.info(f"已提取章节列表，共 {len(self.chapters)} 章")
            
            # 添加章节URL到爬取队列
            for chapter in self.chapters:
                chapter_url = chapter.get('url')
                if chapter_url:
                    # 确保URL是完整的
                    full_chapter_url = chapter_url if chapter_url.startswith('http') else urljoin(self.base_url, chapter_url)
                    logger.info(f"添加章节 URL: {full_chapter_url}")
                    self.db.save_chapter({
                        "novel_id": novel_id,
                        "chapter_index": chapter.get('index', 0),
                        "chapter_title": chapter.get('title', ''),
                        "chapter_url": full_chapter_url
                    })
            
            # 确定最大章节数
            max_chapters = await self.determine_max_chapter(novel_id, url)
            logger.info(f"确定最大章节数为: {max_chapters}")
            
            # 应用章节限制
            if limit_chapters is not None and limit_chapters > 0:
                max_chapters = min(max_chapters, limit_chapters)
                logger.info(f"限制爬取前 {max_chapters} 章")
            
            # 设置并行爬取批次大小
            batch_size = min(3, max_chapters)  # 最多并行3个章节
            logger.info(f"设置并行爬取批次大小: {batch_size}")
            
            # 分批处理章节
            processed_chapters = 0
            while processed_chapters < max_chapters:
                # 计算当前批次要处理的章节数
                remaining_chapters = max_chapters - processed_chapters
                current_batch_size = min(batch_size, remaining_chapters)
                
                # 处理当前批次
                processed = await self.parallel_process_chapters(current_batch_size)
                if processed == 0:
                    logger.warning("当前批次没有处理任何章节，可能发生错误")
                    break
                    
                processed_chapters += processed
                logger.info(f"已处理 {processed_chapters}/{max_chapters} 章")
                
                # 如果还有剩余章节，等待一段时间再继续
                if processed_chapters < max_chapters:
                    await asyncio.sleep(5)  # 等待5秒再处理下一批
            
        except Exception as e:
            logger.error(f"爬取小说时发生错误: {str(e)}")
            logger.error(traceback.format_exc())
        finally:
            if hasattr(self, 'browser') and self.browser is not None:
                await self.close_browser()
            if hasattr(self, 'db') and self.db is not None:
                await self.db.close()

    async def parallel_process_chapters(self, num_chapters):
        """并行处理多个章节"""
        if not hasattr(self, 'chapters') or not self.chapters:
            logger.warning("没有章节可以并行处理")
            return
            
        # 获取要处理的章节
        start_index = self.state.get("current_chapter", 0)
        end_index = min(start_index + num_chapters, len(self.chapters))
        chapters_to_process = self.chapters[start_index:end_index]
        
        if not chapters_to_process:
            logger.warning("没有找到要处理的章节")
            return
            
        logger.info(f"开始并行处理 {len(chapters_to_process)} 个章节")
        
        # 确保浏览器上下文已初始化
        if not hasattr(self, 'context') or self.context is None:
            logger.error("浏览器上下文未初始化")
            return
            
        # 设置并发限制
        max_concurrent = min(3, len(chapters_to_process))  # 最多同时处理3个章节
        logger.info(f"设置最大并发数为: {max_concurrent}")
        
        # 为每个章节创建单独的页面
        pages = []
        for i in range(max_concurrent):
            try:
                page = await self.context.new_page()
                # 设置更长的超时时间
                page.set_default_navigation_timeout(60000)  # 60秒
                page.set_default_timeout(60000)  # 60秒
                pages.append(page)
                logger.info(f"成功创建页面 {i+1}/{max_concurrent}")
            except Exception as e:
                logger.error(f"创建新页面失败: {e}")
                # 如果创建页面失败，关闭已创建的页面
                for p in pages:
                    await p.close()
                return
                
        if not pages:
            logger.error("没有成功创建任何页面，无法并行处理")
            return
            
        # 并行访问章节
        async def process_chapter(index, chapter, page):
            chapter_index = start_index + index
            chapter_url = chapter.get("url")
            
            if not chapter_url:
                logger.warning(f"章节 {chapter_index} 没有URL")
                return None
                
            # 添加重试机制
            max_retries = 3
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    # 确保URL是完整的
                    full_chapter_url = chapter_url if chapter_url.startswith('http') else urljoin(self.base_url, chapter_url)
                    
                    # 访问章节页面
                    await page.goto(full_chapter_url, timeout=60000)  # 60秒超时
                    await page.wait_for_load_state('networkidle', timeout=60000)  # 60秒超时
                    
                    # 获取页面内容
                    html = await page.content()
                    
                    # 提取章节内容
                    chapter_title, chapter_content, is_complete = await self.fetch_chapter_content(full_chapter_url, chapter_index)
                    
                    if chapter_content:
                        return {
                            "index": chapter_index,
                            "title": chapter_title,
                            "content": chapter_content,
                            "url": full_chapter_url,
                            "is_complete": is_complete
                        }
                        
                    logger.warning(f"章节 {chapter_index} 内容提取失败")
                    retry_count += 1
                    if retry_count < max_retries:
                        logger.info(f"等待 {retry_count * 2} 秒后重试...")
                        await asyncio.sleep(retry_count * 2)
                    
                except Exception as e:
                    logger.error(f"处理章节 {chapter_index} 时发生错误: {e}")
                    retry_count += 1
                    if retry_count < max_retries:
                        logger.info(f"等待 {retry_count * 2} 秒后重试...")
                        await asyncio.sleep(retry_count * 2)
                    
            return None
                
        # 创建任务并等待结果
        tasks = []
        for i, (chapter, page) in enumerate(zip(chapters_to_process, pages)):
            tasks.append(process_chapter(i, chapter, page))
            
        results = await asyncio.gather(*tasks)
        
        # 关闭页面
        for page in pages:
            await page.close()
            
        # 处理结果
        chapters_content = [r for r in results if r]
        logger.info(f"成功并行处理了 {len(chapters_content)} 个章节")
        
        # 更新当前章节索引
        if chapters_content:
            max_index = max([c["index"] for c in chapters_content])
            self.state["current_chapter"] = max_index + 1
            
        return len(chapters_content)

    async def extract_chapter_links_from_dom(self, page):
        """从DOM中提取章节链接，使用DOM预处理和大模型处理结合的方式"""
        try:
            # 获取页面HTML
            html_content = await page.content()
            
            # 使用DOM预处理提取结构化数据
            logger.info("使用DOM预处理提取章节数据...")
            extracted_data = await self.extract_data_from_dom(html_content, "chapter_list")
            
            # 如果DOM预处理成功提取到足够章节，直接使用
            dom_chapters = extracted_data.get("chapters", [])
            if len(dom_chapters) > 10:  # 如果提取到10个以上章节，认为基本成功
                logger.info(f"DOM预处理成功提取到 {len(dom_chapters)} 个章节")
                
                # 展开按钮处理
                expand_buttons = extracted_data.get("expand_buttons", [])
                if expand_buttons:
                    logger.info(f"检测到 {len(expand_buttons)} 个可能的展开按钮")
                    # 尝试点击展开按钮
                    for button in expand_buttons:
                        selector = button.get("selector")
                        if selector:
                            try:
                                logger.info(f"尝试点击展开按钮: {selector}")
                                await page.click(selector)
                                await asyncio.sleep(2)  # 等待内容加载
                                
                                # 重新获取页面内容并提取
                                html_content = await page.content()
                                extracted_data = await self.extract_data_from_dom(html_content, "chapter_list")
                                dom_chapters = extracted_data.get("chapters", [])
                                logger.info(f"点击展开按钮后，提取到 {len(dom_chapters)} 个章节")
                            except Exception as e:
                                logger.warning(f"点击展开按钮失败: {e}")
                
                # 构建结构化数据提供给大模型验证
                novel_title = extracted_data.get("title", "未知标题")
                novel_author = extracted_data.get("author", "未知作者")
                novel_desc = extracted_data.get("description", "")
                
                # 更新状态
                self.state["novel_title"] = novel_title
                self.state["author"] = novel_author
                
                # 构建章节列表文本
                chapters_text = "\n".join([f"{i+1}. {chapter['title']} - {chapter['url']}" 
                                     for i, chapter in enumerate(dom_chapters)])
                
                # 构建结构化数据
                structured_data = f"""网站标题: {novel_title}
作者: {novel_author}
简介: {novel_desc}

章节列表:
{chapters_text}
"""
                
                # 使用大模型验证章节信息
                logger.info("使用大模型验证章节信息...")
                if CRAWLER_CONFIG['use_claude']:
                    # 使用Claude进行验证
                    result = self.claude_client.analyze_structured_data(structured_data, len(dom_chapters))
                    model_chapters = self.claude_client.parse_chapters_from_response(result)
                else:
                    # 使用DeepSeek进行验证
                    result = self.deepseek_client.analyze_structured_data(structured_data, len(dom_chapters))
                    model_chapters = self.deepseek_client.parse_chapters_from_response(result)
                
                # 检查大模型是否正确解析
                if model_chapters and len(model_chapters) > 0:
                    # 检查响应是否完整
                    if "<<<PROCESSING_COMPLETE>>>" in result:
                        logger.info(f"大模型成功验证 {len(model_chapters)} 个章节，响应完整")
                        is_complete = True
                    else:
                        logger.warning(f"大模型响应不完整，可能缺少部分章节信息")
                        is_complete = False
                    
                    # 记录章节解析结果
                    chapters_to_use = model_chapters if len(model_chapters) >= len(dom_chapters) else dom_chapters
                    logger.info(f"最终使用 {len(chapters_to_use)} 个章节 (DOM: {len(dom_chapters)}, 模型: {len(model_chapters)})")
                    
                    # 更新数据库中小说的状态信息
                    if self.state["novel_id"]:
                        complete_status = "complete" if is_complete else "incomplete"
                        self.db.update_novel(
                            self.state["novel_id"], 
                            {
                                "title": novel_title,
                                "author": novel_author,
                                "description": novel_desc,
                                "chapter_count": len(chapters_to_use),
                                "status": complete_status,
                                "last_updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            }
                        )
                    
                    # 返回章节信息
                    return chapters_to_use, novel_title, novel_author
            
            # 如果DOM预处理提取不到足够章节，使用原来的大模型方法
            logger.info(f"DOM预处理仅提取到 {len(dom_chapters)} 个章节，尝试使用大模型直接提取...")
            
            # 获取当前URL
            url = page.url
            
            # 使用大模型直接分析HTML内容
            from config import PROMPT_TEMPLATES
            
            # 将HTML内容发送给大模型解析
            if CRAWLER_CONFIG['use_claude']:
                # 使用Claude客户端
                prompt = PROMPT_TEMPLATES['chapter_list'].format(content=html_content[:150000])
                response = self.claude_client.call_claude(prompt)
                
                if response and "<<<CHAPTER_START>>>" in response:
                    chapters = self.claude_client.parse_chapters_from_response(response)
                    is_complete = "<<<PROCESSING_COMPLETE>>>" in response
                else:
                    logger.error("Claude未能正确解析章节列表")
                    return [], "", ""
            else:
                # 使用DeepSeek客户端
                prompt = PROMPT_TEMPLATES['chapter_list'].format(content=html_content[:80000])
                response = self.deepseek_client._call_api(prompt)
                
                if response and "<<<CHAPTER_START>>>" in response:
                    chapters = self.deepseek_client.parse_chapters_from_response(response)
                    is_complete = "<<<PROCESSING_COMPLETE>>>" in response
                else:
                    logger.error("DeepSeek未能正确解析章节列表")
                    return [], "", ""
            
            # 提取小说标题和作者
            title_pattern = r"网站标题[：:]\s*(.*?)[\n\r]"
            author_pattern = r"作者[：:]\s*(.*?)[\n\r]"
            
            title_match = re.search(title_pattern, response)
            author_match = re.search(author_pattern, response)
            
            novel_title = title_match.group(1).strip() if title_match else "未知标题"
            novel_author = author_match.group(1).strip() if author_match else "未知作者"
            
            # 更新状态
            self.state["novel_title"] = novel_title
            self.state["author"] = novel_author
            
            # 更新数据库中小说的状态
            if self.state["novel_id"]:
                complete_status = "complete" if is_complete else "incomplete"
                self.db.update_novel(
                    self.state["novel_id"], 
                    {
                        "title": novel_title,
                        "author": novel_author,
                        "chapter_count": len(chapters),
                        "status": complete_status,
                        "last_updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                )
            
            logger.info(f"大模型提取到 {len(chapters)} 个章节")
            return chapters, novel_title, novel_author
            
        except Exception as e:
            logger.error(f"提取章节链接时出错: {e}")
            logger.error(traceback.format_exc())
            return [], "", ""

    async def extract_data_from_dom(self, html, page_type="unknown"):
        """使用DOM预处理从HTML中提取结构化数据"""
        soup = BeautifulSoup(html, 'html.parser')
        result = {}
        
        if page_type == "novel_info" or page_type == "chapter_list":
            # 提取小说基本信息
            title_candidates = [
                soup.select_one('h1.book-title, h1.novel-title, h1.title'),
                soup.select_one('div.book-title, div.novel-title'),
                soup.select_one('meta[property="og:novel:book_name"]'),
                soup.select_one('meta[property="og:title"]'),
                soup.select_one('h1, h2'),
                # 添加更多选择器
                soup.select_one('.book-name'),
                soup.select_one('.novel-name'),
                soup.select_one('h3.title'),
                soup.select_one('div.info h1'),
                soup.select_one('div.info h2')
            ]
            
            # 尝试从标题中提取小说名
            for candidate in title_candidates:
                if candidate:
                    if candidate.name == 'meta':
                        title = candidate.get('content', '').strip()
                    else:
                        title = candidate.text.strip()
                        
                    # 清理标题
                    title = re.sub(r'最新章节.*$', '', title)  # 移除"最新章节"等后缀
                    title = re.sub(r'全文阅读.*$', '', title)  # 移除"全文阅读"等后缀
                    title = re.sub(r'_.*$', '', title)  # 移除下划线后的内容
                    title = re.sub(r'[\s\-_]+', ' ', title)  # 规范化空白字符
                    title = title.strip()
                    
                    if title and len(title) > 1:  # 确保标题不为空且长度大于1
                        result["title"] = title
                        logger.info(f"找到小说标题: {title}")
                        break
            
            # 如果还没找到标题，尝试从URL中提取
            if not result.get("title"):
                url_match = re.search(r'/([^/]+)/?$', self.base_url)
                if url_match:
                    result["title"] = url_match.group(1)
                    logger.info(f"从URL提取标题: {result['title']}")
                    
            # 提取作者信息
            author_candidates = [
                soup.select_one('div.author, span.author'),
                soup.select_one('meta[property="og:novel:author"]'),
                soup.select_one('a[href*="author"]'),
                # 添加更多选择器
                soup.select_one('.author-name'),
                soup.select_one('.writer'),
                soup.select_one('div.info span:contains("作者")')
            ]
            
            for candidate in author_candidates:
                if candidate:
                    if candidate.name == 'meta':
                        author = candidate.get('content', '').strip()
                    else:
                        author_text = candidate.text.strip()
                        # 清理作者名
                        author = re.sub(r'^作者[：:]\s*', '', author_text)
                        author = re.sub(r'[\s\-_]+', ' ', author)
                        author = author.strip()
                        
                    if author and len(author) > 1:  # 确保作者名不为空且长度大于1
                        result["author"] = author
                        logger.info(f"找到作者: {author}")
                        break
            
            # 提取简介
            desc_candidates = [
                soup.select_one('div.intro, div.description, div.summary'),
                soup.select_one('meta[property="og:description"]'),
                soup.select_one('meta[name="description"]')
            ]
            
            for candidate in desc_candidates:
                if candidate:
                    if candidate.name == 'meta':
                        result["description"] = candidate.get('content', '').strip()
                    else:
                        result["description"] = candidate.text.strip()
                    break
                
            # 查找章节列表
            if page_type == "chapter_list":
                chapters = []
                
                # 查找可能的章节列表容器
                chapter_containers = [
                    soup.select('div.listmain a, ul.chapter-list a, div.chapter-list a'),
                    soup.select('div.volume a, ul.volume a'),
                    soup.select('div.list a'),
                    soup.select('a[href*=".html"]')
                ]
                
                for container in chapter_containers:
                    if container and len(container) > 0:
                        for link in container:
                            href = link.get('href', '')
                            title = link.text.strip()
                            
                            # 过滤有效的章节链接（通常包含数字和.html）
                            if (href and title and re.search(r'/\d+\.html$', href) and 
                                not any(keyword in title.lower() for keyword in ['登录', '注册', '加入', '收藏'])):
                                chapters.append({
                                    "title": self.clean_chapter_title(title),
                                    "url": href
                                })
                        
                        if len(chapters) > 0:
                            break
                
                # 排序章节（通常按URL中的数字排序）
                chapters.sort(key=lambda x: int(re.search(r'/(\d+)\.html$', x['url']).group(1)) 
                               if re.search(r'/(\d+)\.html$', x['url']) else 0)
                
                result["chapters"] = chapters
                
                # 查找可能的展开按钮
                expand_buttons = []
                for button in soup.select('a, button, .more, .show-more, .expand, .allshow'):
                    text = button.text.strip().lower()
                    if any(keyword in text for keyword in ['展开', '更多', '全部']):
                        expand_buttons.append({
                            "text": button.text.strip(),
                            "selector": self._get_element_selector(button)
                        })
                
                if expand_buttons:
                    result["expand_buttons"] = expand_buttons
        
        elif page_type == "chapter_content":
            # 提取章节标题
            title_candidates = [
                soup.select_one('h1.chapter-title, h1.title'),
                soup.select_one('div.chapter-title, div.title'),
                soup.select_one('h1, h2')
            ]
            
            for candidate in title_candidates:
                if candidate:
                    result["title"] = candidate.text.strip()
                    break
            
            # 提取章节内容
            content_candidates = [
                soup.select_one('#content, .content'),
                soup.select_one('.chapter-content, .article-content'),
                soup.select_one('.read-content, .novel-content')
            ]
            
            for candidate in content_candidates:
                if candidate:
                    # 移除脚本和样式
                    for script in candidate.find_all('script'):
                        script.decompose()
                    for style in candidate.find_all('style'):
                        style.decompose()
                    
                    # 提取纯文本内容
                    content = candidate.get_text('\n', strip=True)
                    result["content"] = self.clean_chapter_content(content)
                    break
            
            # 查找下一章链接
            next_candidates = [
                soup.select_one('a.next, a.next-chapter'),
                soup.select_one('a:contains("下一章"), a:contains("下一页")')
            ]
            
            for candidate in next_candidates:
                if candidate:
                    result["next_chapter"] = {
                        "text": candidate.text.strip(),
                        "url": candidate.get('href', '')
                    }
                    break
        
        return result
        
    def _get_element_selector(self, element):
        """尝试为元素构建简单的CSS选择器"""
        if element.get('id'):
            return f"#{element['id']}"
        elif element.get('class'):
            return f".{' .'.join(element['class'])}"
        else:
            return element.name

async def main():
    crawler = NovelCrawler()
    novel_url = CRAWLER_CONFIG['base_url']  # 直接使用配置中的完整URL
    
    # 限制爬取章节数，加快测试，设置为None可爬取全部
    limit_chapters = 3  # 只爬取前3章进行测试
    
    await crawler.crawl_novel(novel_url, limit_chapters)

if __name__ == "__main__":
    asyncio.run(main()) 