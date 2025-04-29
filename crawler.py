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
from database import Database
from deepseek_client import DeepSeekClient
from config import CRAWLER_CONFIG, STORAGE_CONFIG
from urllib.parse import urljoin, urlparse

# 配置日志
def setup_logging():
    # 创建日志目录
    os.makedirs('logs', exist_ok=True)
    
    # 配置日志格式
    log_format = '%(asctime)s [%(levelname)s] %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    
    # 文件处理器
    file_handler = logging.FileHandler(
        f'logs/crawler_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.log',
        encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter(log_format, date_format))
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format, date_format))
    
    # 配置根日志记录器
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logging()

class NovelCrawler:
    def __init__(self):
        self.db = Database()
        self.deepseek_client = DeepSeekClient()
        self.base_url = CRAWLER_CONFIG['base_url']
        self.headers = CRAWLER_CONFIG['headers']
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
        """初始化浏览器"""
        try:
            logger.info("开始初始化浏览器")
            self.playwright = await async_playwright().start()
            browser_config = {
                'headless': False,
                'channel': 'firefox',  # 使用 Firefox 浏览器
                'args': [
                    '--disable-gpu',
                    '--disable-dev-shm-usage',
                    '--disable-setuid-sandbox',
                    '--no-sandbox',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process',
                    '--disable-site-isolation-trials'
                ]
            }
            
            logger.info("正在启动 Firefox 浏览器")
            self.browser = await self.playwright.firefox.launch(**browser_config)
            
            # 创建浏览器上下文时添加性能优化
            context_options = {
                'user_agent': self.headers['User-Agent'],
                'viewport': {'width': 1280, 'height': 800},
                'java_script_enabled': True,
                'ignore_https_errors': True,
                'bypass_csp': True,
                'accept_downloads': False,
                'has_touch': False,
                'is_mobile': False,
                'color_scheme': 'light',
                'forced_colors': 'none',
                'reduced_motion': 'no-preference',
                'screen': {
                    'width': 1280,
                    'height': 800,
                    'color_depth': 24
                }
            }
            
            logger.info("正在创建浏览器上下文")
            self.context = await self.browser.new_context(**context_options)
            
            # 配置浏览器上下文忽略HTTPS错误
            self.context.set_default_timeout(60000)
            
            # 阻止非必要的资源加载
            if self.enable_js_blocking:
                logger.info("配置资源加载策略")
                await self.context.route("**/*.{png,jpg,jpeg,gif,svg,pdf,mp4,webp}", 
                    lambda route: route.abort() if self.skip_images else route.continue_())
                
                await self.context.route("**/{ads,analytics,google-analytics,doubleclick}*.*", 
                    lambda route: route.abort())
            
            self.page = await self.context.new_page()
            self.page.set_default_navigation_timeout(self.page_timeout)
            
            # 设置页面错误处理
            self.page.on("crash", lambda: logger.error("页面崩溃"))
            
            async def filter_page_errors(err):
                error_message = str(err)
                if "localStorage" not in error_message:
                    logger.error(f"页面错误: {error_message}")
            
            self.page.on("pageerror", filter_page_errors)
            
            # 注入localStorage模拟代码
            await self.page.add_init_script("""
            if (!window.localStorage) {
                console.log('正在模拟localStorage...');
                const storage = {};
                Object.defineProperty(window, 'localStorage', {
                    value: {
                        getItem: function (key) { 
                            return key in storage ? storage[key] : null; 
                        },
                        setItem: function (key, value) { 
                            storage[key] = value.toString(); 
                            return true;
                        },
                        removeItem: function (key) { 
                            delete storage[key]; 
                            return true;
                        },
                        clear: function () {
                            Object.keys(storage).forEach(key => delete storage[key]);
                            return true;
                        },
                        key: function(index) {
                            return Object.keys(storage)[index] || null;
                        },
                        get length() {
                            return Object.keys(storage).length;
                        }
                    },
                    writable: false,
                    configurable: true
                });
                
                window.addEventListener('error', function(e) {
                    if (e.message.includes('localStorage')) {
                        console.log('拦截到localStorage错误:', e.message);
                        e.preventDefault();
                        e.stopPropagation();
                        return true;
                    }
                }, true);
            }
            """)
            
            await self.context.route("**/*.js", self.handle_js_requests)
            
            self.browser_initialized = True
            logger.info("浏览器初始化成功")
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
        except Exception as e:
            print(f"关闭浏览器出错: {e}")

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
        cleaned_content = self.clean_chapter_content(content)
        
        # 按照指定格式生成文件名：小说名称-章节序号-章节名称
        filename = f"{novel_title}-第{chapter_index+1}章-{clean_name}.txt"
        
        # 移除文件名中的非法字符
        filename = "".join(c for c in filename if c.isalnum() or c in "._- ")
        filepath = os.path.join(novel_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(cleaned_content)
        
        print(f"[Python] [文件] 已保存: {filepath}")
        return filepath

    async def handle_js_requests(self, route):
        """处理JavaScript请求"""
        try:
            # 继续原始请求
            await route.continue_()
        except Exception as e:
            # 如果有错误，提供一个空的JS响应
            print(f"[Playwright] [请求] 处理JS请求时出错: {e}")
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
            logging.info(f"初始内容长度: {initial_length} 字符")
            
            # 先快速滚动到底部
            await page.evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
            await asyncio.sleep(3)
            
            # 执行额外的内容加载检查
            await page.evaluate('''() => {
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
            
            await asyncio.sleep(2)
            
            # 再次滚动确保所有内容加载
            await page.evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
            await asyncio.sleep(2)
            
            # 获取最终内容
            final_content = await page.content()
            final_length = len(final_content)
            logging.info(f"滚动后内容长度: {final_length} 字符，增加了 {final_length - initial_length} 字符")
            
            # 对某些特定的网站使用特殊处理
            await page.evaluate('''() => {
                // 尝试执行网站特定的脚本解锁内容
                if (document.querySelector('.read-content')) {
                    // 部分网站通过js控制显示内容
                    document.querySelectorAll('.read-content')[0].style.height = 'auto';
                    document.querySelectorAll('.read-content')[0].style.overflow = 'visible';
                }
            }''')
            
            await asyncio.sleep(1)
            
            # 再次获取内容检查变化
            last_content = await page.content()
            if len(last_content) > final_length:
                logging.info(f"特殊处理后内容长度: {len(last_content)} 字符，再增加了 {len(last_content) - final_length} 字符")
            
            return last_content
            
        except Exception as e:
            logging.error(f"滚动页面时发生错误: {e}")
            return await page.content()  # 发生错误时返回当前内容

    async def fetch_chapter_content(self, chapter_url, chapter_index, chapter_info=None):
        """获取单个章节的内容"""
        try:
            # 创建新的页面
            page = await self.context.new_page()
            
            try:
                # 访问章节页面
                logging.info(f"正在访问章节页面: {chapter_url}")
                response = await page.goto(chapter_url, timeout=180000)
                
                # 检查页面是否可以访问
                if not response or response.status >= 400:
                    logging.warning(f"章节页面无法访问: {chapter_url}，状态码: {response.status if response else 'N/A'}")
                    return None
                
                # 等待页面加载
                await page.wait_for_load_state("networkidle", timeout=60000)
                
                # 记录初始页面标题
                page_title = await page.title()
                logging.info(f"页面标题: {page_title}")
                
                # 检查是否是有效的章节页
                if "404" in page_title or "找不到" in page_title or "不存在" in page_title:
                    logging.warning(f"章节页面可能不存在: {chapter_url}，标题: {page_title}")
                    return None
                
                # 滚动到底部并获取完整内容
                full_html = await self.scroll_to_bottom(page)
                
                # 首先尝试直接从DOM提取内容
                content = ""
                title = await page.title()
                
                # 尝试常见的内容容器选择器
                content_selectors = [
                    "#content", 
                    ".article-content", 
                    ".chapter-content", 
                    ".content", 
                    ".read-content", 
                    "#chapterContent", 
                    ".panel-content",
                    "#txtContent",
                    ".txt-content",
                    ".chapter-c",
                    "#BookText",
                    "#booktext"
                ]
                
                for selector in content_selectors:
                    try:
                        element = await page.query_selector(selector)
                        if element:
                            dom_content = await element.inner_text()
                            if dom_content and len(dom_content) > len(content):
                                logging.info(f"从选择器 {selector} 提取到内容，长度: {len(dom_content)} 字符")
                                content = dom_content
                    except Exception as e:
                        logging.error(f"提取选择器 {selector} 内容时出错: {e}")
                
                # 如果DOM提取失败或内容太短，再尝试分析页面
                if not content or len(content) < 1000:
                    logging.info("DOM提取不完整，尝试使用API分析页面...")
                    
                    # 分析页面内容
                    state_info = {
                        "phase": "chapter_content",
                        "novel_title": self.state["novel_title"],
                        "author": self.state["author"],
                        "current_chapter": chapter_index
                    }
                    
                    result = self.deepseek_client.all_in_one_analysis(full_html, state_info)
                    
                    if result.get("page_type") == "chapter_content":
                        chapter_data = result.get("chapter_data", {})
                        api_content = chapter_data.get("content", "")
                        api_title = chapter_data.get("title", f"第{chapter_index}章")
                        
                        # 如果API提取的内容更长，使用API结果
                        if api_content and len(api_content) > len(content):
                            logging.info(f"使用API提取的内容，长度: {len(api_content)} 字符")
                            content = api_content
                            title = api_title

                # 最终检查
                if not content or len(content) < 300:
                    # 最后尝试提取所有正文段落
                    try:
                        paragraphs = await page.evaluate('''() => {
                            // 获取所有可能包含正文的段落
                            const paragraphs = Array.from(document.querySelectorAll('p, div'));
                            
                            // 过滤出可能是正文内容的段落
                            return paragraphs
                                .filter(p => {
                                    // 排除明显不是正文的元素
                                    if (p.querySelector('a, button, input, script')) return false;
                                    
                                    // 获取文本内容
                                    const text = p.textContent || '';
                                    
                                    // 有效段落应该有适当的长度
                                    return text.length > 10 && text.length < 500;
                                })
                                .map(p => p.textContent)
                                .join('\\n\\n');
                        }''')
                        
                        if paragraphs and len(paragraphs) > len(content):
                            logging.info(f"从段落提取内容，长度: {len(paragraphs)} 字符")
                            content = paragraphs
                    except Exception as e:
                        logging.error(f"提取段落内容时出错: {e}")
                
                # 清理内容
                cleaned_content = self.clean_chapter_content(content)
                
                # 从URL或标题提取章节标题
                chapter_title = ""
                
                # 如果是URL递增生成的章节，尝试从URL和页面标题提取章节信息
                if chapter_info and "title" in chapter_info and chapter_info["title"].startswith("第") and chapter_info["title"].endswith("章"):
                    # 使用URL递增生成的标题
                    chapter_title = chapter_info["title"]
                    
                    # 尝试从页面标题获取更具体的章节名
                    try:
                        page_title_clean = self.clean_chapter_title(title)
                        if page_title_clean:
                            # 提取章节名，通常格式为"第X章 章节名"
                            title_match = re.search(r'第.*?章\s+(.*)', page_title_clean)
                            if title_match:
                                specific_title = title_match.group(1).strip()
                                if specific_title:
                                    chapter_title = f"{chapter_info['title']} {specific_title}"
                    except Exception as e:
                        logging.error(f"提取章节标题时出错: {e}")
                else:
                    # 获取干净的章节名称
                    chapter_title = self.get_clean_chapter_name(title, chapter_index)
                
                # 最终结果
                content_length = len(cleaned_content) if cleaned_content else 0
                logging.info(f"章节 {chapter_index} 最终内容长度: {content_length} 字符")
                
                # 检查是否成功提取内容
                if cleaned_content and content_length > 300:
                    return {
                        "index": chapter_index,
                        "title": chapter_title,
                        "content_cn": cleaned_content,
                        "content_en": "",
                        "summary_100": "",
                        "summary": "",
                        "outline_structured": None,
                        "storyboard_structured": None,
                        "url": chapter_url
                    }
                else:
                    logging.error(f"章节 {chapter_index} 内容提取失败，内容长度: {content_length} 字符")
                    return None
            
            except Exception as e:
                logging.error(f"获取章节 {chapter_index} 内容时出错: {e}")
                logging.error(traceback.format_exc())
                return None
            
            finally:
                # 关闭页面
                await page.close()
                
        except Exception as e:
            logging.error(f"处理章节 {chapter_index} 时发生错误: {e}")
            return None

    async def crawl_novel(self, url: str, limit_chapters: int = 0):
        try:
            # 初始化浏览器
            await self.init_browser()
            
            # 访问小说页面获取章节列表
            logging.info(f"正在访问页面: {url}")
            await self.page.goto(url, timeout=180000)
            
            # 滚动到底部确保加载所有章节
            await self.scroll_to_bottom(self.page)
            
            # 获取页面内容
            html = await self.page.content()
            
            # 分析章节列表页
            result = self.deepseek_client.all_in_one_analysis(html, self.state)
            
            # 保存小说基本信息
            title = result.get("title", "未知")
            author = result.get("author", "未知")
            chapters = result.get("chapters", [])
            
            logging.info(f"获取小说信息: {title} - 作者: {author}")
            
            # 更新爬虫状态
            self.state["novel_title"] = title
            self.state["author"] = author
            self.state["chapters"] = chapters
            self.state["phase"] = "chapter_list"
            self.state["novel_id"] = self.db.insert_novel(
                title=title,
                author=author,
                description=result.get("description", ""),
                source_url=url,
                category_id=1
            )
            
            # 尝试从DeepSeek API获取章节列表
            chapter_urls = []
            if result.get("page_type") == "chapter_list" and chapters:
                logging.info(f"已提取章节列表，共 {len(chapters)} 章")
                
                for chapter in chapters:
                    chapter_url = chapter.get("url")
                    if not chapter_url and "selector" in chapter:
                        # 如果没有直接URL，尝试从选择器获取
                        selector = chapter.get("selector")
                        try:
                            element = await self.page.query_selector(selector)
                            if element:
                                href = await element.get_attribute("href")
                                if href:
                                    if href.startswith("http"):
                                        chapter_url = href
                                    else:
                                        # 相对路径转绝对路径
                                        base_url = self.page.url
                                        chapter_url = urljoin(base_url, href)
                        except Exception as e:
                            logging.error(f"获取章节链接失败: {e}")
                    
                    # 修复URL路径问题，确保所有URL都是绝对路径
                    if chapter_url:
                        # 如果是相对路径，转换为绝对路径
                        if not chapter_url.startswith('http'):
                            base_url = self.page.url
                            chapter_url = urljoin(base_url, chapter_url)
                        
                        chapter_urls.append({
                            "index": len(chapter_urls),
                            "url": chapter_url,
                            "title": chapter.get("title", f"第{len(chapter_urls)+1}章")
                        })
                        logging.info(f"添加章节 URL: {chapter_url}")
            
            # 如果没有找到章节列表或章节数量过少，尝试从DOM直接提取
            if len(chapter_urls) < 5:
                logging.info("DeepSeek API提取章节数量过少，尝试从DOM直接提取...")
                dom_chapters = await self.extract_chapter_links_from_dom(self.page)
                
                if len(dom_chapters) > len(chapter_urls):
                    logging.info(f"从DOM提取到更多章节: {len(dom_chapters)} > {len(chapter_urls)}")
                    chapter_urls = dom_chapters
            
            # 强制使用URL递增方式，无论是否找到足够的章节链接
            logging.info("启用URL递增备用方案...")
            
            # 提取小说ID
            novel_id = None
            path_parts = urlparse(url).path.strip('/').split('/')
            for part in path_parts:
                if part.isdigit():
                    novel_id = part
                    break
            
            if not novel_id:
                novel_id = "43863"  # 默认使用星门的ID
                
            # 构建URL模式
            base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
            base_pattern = f"{base_url}/html/{novel_id}/{{0}}.html"
            
            # 清空之前的章节列表
            chapter_urls = []
            
            # 生成所有章节URL
            max_chapter = 640  # 设置最大章节数，比实际章节数多一些
            for i in range(1, max_chapter + 1):
                chapter_urls.append({
                    "index": i - 1,
                    "url": base_pattern.format(i),
                    "title": f"第{i}章"
                })
            
            logging.info(f"URL递增方式生成了 {len(chapter_urls)} 个章节URL")
            
            # 限制章节数量
            if limit_chapters is not None and limit_chapters > 0 and len(chapter_urls) > limit_chapters:
                chapter_urls = chapter_urls[:limit_chapters]
                logging.info(f"限制爬取前 {limit_chapters} 章")
            
            # 如果没有找到章节URL，无法继续
            if not chapter_urls:
                logging.warning("没有找到任何章节URL，无法继续爬取")
                return
                
            # 并行爬取章节内容
            batch_size = min(max(1, self.parallel_chapters), len(chapter_urls))
            logging.info(f"设置并行爬取批次大小: {batch_size}")
            
            # 记录实际存在的章节URL
            valid_chapter_urls = []
            
            # 分批次爬取
            for i in range(0, len(chapter_urls), batch_size):
                batch = chapter_urls[i:i+batch_size]
                logging.info(f"开始爬取第 {i//batch_size + 1} 批次，包含 {len(batch)} 个章节")
                
                # 并行处理一批章节
                tasks = []
                for chapter in batch:
                    tasks.append(self.fetch_chapter_content(
                        chapter["url"], 
                        chapter["index"],
                        chapter
                    ))
                
                # 等待所有任务完成
                results = await asyncio.gather(*tasks)
                
                # 处理结果
                successful_chapters = 0
                for result in results:
                    if result:
                        # 保存到文件
                        self.save_to_file(
                            self.state["novel_title"],
                            result["index"],
                            result["title"],
                            result["content_cn"]
                        )
                        
                        # 保存到数据库
                        self.db.insert_chapter(
                            novel_id=self.state["novel_id"],
                            chapter_index=result["index"],
                            chapter_title=result["title"],
                            chapter_url=result["url"],
                            content_cn=result["content_cn"],
                            content_en=result.get("content_en", ""),
                            summary_100=result.get("summary_100", ""),
                            summary=result.get("summary", "")
                        )
                        
                        # 记录有效的章节URL
                        valid_chapter_urls.append(result["url"])
                        
                        # 更新状态
                        self.state["completed_chapters"].append(result["index"])
                        self.state["current_chapter"] = max(self.state["current_chapter"], result["index"] + 1)
                        
                        successful_chapters += 1
                
                logging.info(f"第 {i//batch_size + 1} 批次完成，成功爬取 {successful_chapters}/{len(batch)} 个章节")
                
                # 对于URL递增方式，如果连续5个章节都无法获取内容，认为已到达最后一章
                if len(valid_chapter_urls) > 0 and successful_chapters == 0:
                    consecutive_failures = i + batch_size - len(valid_chapter_urls)
                    if consecutive_failures >= 5:
                        logging.info(f"连续 {consecutive_failures} 个章节无法获取内容，可能已到达最后一章")
                        break
                
                # 简单的反爬虫措施
                if i + batch_size < len(chapter_urls):
                    delay = 5 + (0.5 * batch_size)  # 根据批次大小调整延迟
                    logging.info(f"等待 {delay} 秒后继续下一批次...")
                    await asyncio.sleep(delay)
            
            logging.info(f"爬取完成，总共爬取了 {len(self.state['completed_chapters'])} 章")
                
        except Exception as e:
            logging.error(f"爬虫运行出错: {e}")
            logging.error(traceback.format_exc())
            raise
        
        finally:
            # 关闭浏览器
            if self.browser:
                await self.close_browser()
            self.db.close()

    async def parallel_process_chapters(self, num_chapters):
        """并行处理多个章节"""
        if not self.state["chapters"] or len(self.state["chapters"]) == 0:
            print("[Playwright] [爬虫] 没有章节可以并行处理")
            return
            
        # 获取要处理的章节
        start_index = self.state["current_chapter"]
        end_index = min(start_index + num_chapters, len(self.state["chapters"]))
        chapters_to_process = self.state["chapters"][start_index:end_index]
        
        if not chapters_to_process:
            print("[Playwright] [爬虫] 没有找到要处理的章节")
            return
            
        print(f"[Playwright] [爬虫] 开始并行处理 {len(chapters_to_process)} 个章节")
        
        # 为每个章节创建单独的页面
        pages = []
        for i in range(len(chapters_to_process)):
            try:
                page = await self.context.new_page()
                pages.append(page)
            except Exception as e:
                print(f"[Playwright] [爬虫] 创建新页面失败: {e}")
                
        if not pages:
            print("[Playwright] [爬虫] 没有成功创建任何页面，无法并行处理")
            return
            
        # 并行访问章节
        async def process_chapter(index, chapter, page):
            chapter_index = start_index + index
            chapter_selector = chapter.get("selector")
            
            if not chapter_selector:
                print(f"[Playwright] [爬虫] 章节 {chapter_index} 没有选择器")
                return None
                
            try:
                # 回到小说主页
                await page.goto(self.base_url, timeout=30000)
                await asyncio.sleep(2)
                
                # 检查选择器是否存在
                selector_exists = await page.evaluate(f"!!document.querySelector('{chapter_selector.replace('\'', '\\\'')}')")
                if not selector_exists:
                    print(f"[Playwright] [爬虫] 章节 {chapter_index} 选择器 '{chapter_selector}' 不存在")
                    return None
                    
                # 点击章节链接
                await page.click(chapter_selector)
                await asyncio.sleep(2)
                
                # 获取页面内容
                html = await page.content()
                
                # 分析页面
                analysis = self.deepseek_client.all_in_one_analysis(html, {
                    "phase": "chapter_content",
                    "novel_title": self.state["novel_title"],
                    "author": self.state["author"],
                    "current_chapter": chapter_index
                })
                
                if analysis.get('page_type') == 'chapter_content':
                    chapter_data = analysis.get('chapter_data', {})
                    if chapter_data and chapter_data.get("content"):
                        return {
                            "index": chapter_index,
                            "title": chapter_data.get("title", f"第{chapter_index}章"),
                            "content": chapter_data.get("content", ""),
                            "summary": chapter_data.get("summary", ""),
                            "url": page.url
                        }
                        
                print(f"[Playwright] [爬虫] 章节 {chapter_index} 内容提取失败")
                return None
                
            except Exception as e:
                print(f"[Playwright] [爬虫] 处理章节 {chapter_index} 时发生错误: {e}")
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
        print(f"[Playwright] [爬虫] 成功并行处理了 {len(chapters_content)} 个章节")
        
        # 批量翻译
        contents_to_translate = [c["content"] for c in chapters_content]
        english_contents = []
        
        if contents_to_translate:
            # 如果有batch_translate方法就使用批量翻译
            if hasattr(self.deepseek_client, 'batch_translate'):
                english_contents = self.deepseek_client.batch_translate(contents_to_translate)
            else:
                # 否则逐个翻译
                for content in contents_to_translate:
                    english_contents.append(self.deepseek_client.translate_to_english(content))
        
        # 保存章节内容
        for i, chapter in enumerate(chapters_content):
            try:
                # 保存到本地文件
                self.save_to_file(
                    self.state["novel_title"],
                    chapter["index"],
                    chapter["title"],
                    chapter["content"]
                )
                
                # 保存到数据库
                self.db.insert_chapter(
                    novel_id=self.state["novel_id"],
                    chapter_index=chapter["index"],
                    chapter_title=chapter["title"],
                    chapter_url=chapter["url"],
                    content_cn=chapter["content"],
                    content_en=english_contents[i] if i < len(english_contents) else "",
                    summary_100=chapter.get("summary_100", ""),
                    summary=chapter.get("summary", "")
                )
                
                # 更新状态
                self.state["completed_chapters"].append(chapter["index"])
                print(f"[Playwright] [爬虫] 已保存第 {chapter['index']} 章: {chapter['title']}")
                
            except Exception as e:
                print(f"[Playwright] [爬虫] 保存章节 {chapter['index']} 时发生错误: {e}")
                
        # 更新当前章节索引
        if chapters_content:
            max_index = max([c["index"] for c in chapters_content])
            self.state["current_chapter"] = max_index + 1
            
        return len(chapters_content)

    async def extract_chapter_links_from_dom(self, page):
        """直接从DOM提取章节链接，不依赖DeepSeek API"""
        logging.info("开始从DOM直接提取章节链接...")
        
        try:
            # 常见的章节列表容器选择器
            container_selectors = [
                "#chapter-list", 
                ".chapter-list", 
                "#chapters", 
                ".chapters",
                "#list", 
                ".list", 
                "#chapterlist", 
                ".chapterlist",
                "#directory", 
                ".directory",
                ".catalog",
                "#catalog"
            ]
            
            chapter_urls = []
            
            # 先尝试通过容器选择器定位章节列表区域
            for selector in container_selectors:
                try:
                    container = await page.query_selector(selector)
                    if container:
                        logging.info(f"找到章节列表容器: {selector}")
                        
                        # 从容器中提取所有链接
                        links = await container.query_selector_all("a")
                        
                        if links and len(links) > 0:
                            logging.info(f"从容器 {selector} 中找到 {len(links)} 个链接")
                            
                            for i, link in enumerate(links):
                                try:
                                    href = await link.get_attribute("href")
                                    text = await link.inner_text()
                                    
                                    # 过滤非章节链接（通常章节链接包含数字或特定模式）
                                    if href and (re.search(r'/\d+\.html', href) or 
                                                re.search(r'chapter', href) or 
                                                re.search(r'chap', href)):
                                        
                                        # 处理相对URL
                                        if not href.startswith('http'):
                                            base_url = page.url
                                            href = urljoin(base_url, href)
                                        
                                        chapter_urls.append({
                                            "index": len(chapter_urls),
                                            "title": text.strip() or f"第{len(chapter_urls)+1}章",
                                            "url": href
                                        })
                                        
                                except Exception as e:
                                    logging.error(f"提取链接信息出错: {e}")
                            
                            # 如果找到足够多的链接，就不继续查找了
                            if len(chapter_urls) > 5:
                                break
                except Exception as e:
                    logging.error(f"处理容器 {selector} 时出错: {e}")
            
            # 如果通过容器选择器没有找到足够多的链接，尝试直接选择所有链接
            if len(chapter_urls) < 5:
                logging.info("通过容器选择器未找到足够的章节链接，尝试直接选择所有链接...")
                
                # 获取页面中所有的链接
                all_links = await page.query_selector_all("a")
                logging.info(f"页面共有 {len(all_links)} 个链接")
                
                # 过滤出可能的章节链接
                for link in all_links:
                    try:
                        href = await link.get_attribute("href")
                        text = await link.inner_text()
                        
                        # 判断是否为章节链接：章节链接通常包含数字和中文数字，或包含"章"字
                        is_chapter = False
                        
                        if href and text:
                            # 判断链接文本是否为章节标题
                            if re.search(r'第[0-9一二三四五六七八九十百千]+章', text) or \
                               re.search(r'[0-9]+\.', text) or \
                               (re.search(r'/\d+\.html', href) and len(text.strip()) > 1):
                                is_chapter = True
                        
                        if is_chapter:
                            # 处理相对URL
                            if not href.startswith('http'):
                                base_url = page.url
                                href = urljoin(base_url, href)
                            
                            # 检查是否已存在相同URL
                            if not any(item["url"] == href for item in chapter_urls):
                                chapter_urls.append({
                                    "index": len(chapter_urls),
                                    "title": text.strip() or f"第{len(chapter_urls)+1}章",
                                    "url": href
                                })
                    except Exception as e:
                        logging.error(f"处理链接时出错: {e}")
            
            # 按顺序排序章节（如果章节标题包含数字）
            try:
                # 尝试提取章节序号用于排序
                def get_chapter_number(chapter):
                    title = chapter["title"]
                    match = re.search(r'第(\d+)章', title)
                    if match:
                        return int(match.group(1))
                    match = re.search(r'(\d+)', title)
                    if match:
                        return int(match.group(1))
                    return chapter["index"]
                
                chapter_urls.sort(key=get_chapter_number)
                
                # 重新分配索引
                for i, chapter in enumerate(chapter_urls):
                    chapter["index"] = i
                    
            except Exception as e:
                logging.error(f"章节排序时出错: {e}")
            
            logging.info(f"DOM提取总共找到 {len(chapter_urls)} 个章节链接")
            return chapter_urls
            
        except Exception as e:
            logging.error(f"从DOM提取章节链接时出错: {e}")
            logging.error(traceback.format_exc())
            return []

async def main():
    crawler = NovelCrawler()
    novel_url = CRAWLER_CONFIG['base_url']  # 直接使用配置中的完整URL
    
    # 限制爬取章节数，加快测试，设置为None可爬取全部
    limit_chapters = 3  # 只爬取前3章进行测试
    
    await crawler.crawl_novel(novel_url, limit_chapters)

if __name__ == "__main__":
    asyncio.run(main()) 