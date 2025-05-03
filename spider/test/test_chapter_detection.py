import asyncio
import logging
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from spider.crawler import NovelCrawler, setup_logging
from config import CRAWLER_CONFIG

# 配置日志记录
logger = setup_logging()

async def test_chapter_list_parsing():
    """测试从章节列表页解析章节信息的功能"""
    crawler = NovelCrawler()
    
    try:
        # 初始化浏览器
        await crawler.init_browser()
        
        # 测试几个不同的小说URL
        test_urls = [
            CRAWLER_CONFIG['base_url'],  # 配置中的默认URL
            "https://www.bqgl.cc/look/49988/",  # 其他小说URL用于测试
        ]
        
        for url in test_urls:
            logger.info(f"\n----- 开始测试URL: {url} -----")
            
            try:
                # 访问小说章节列表页
                await crawler.page.goto(url, timeout=30000)
                html_content = await crawler.page.content()
                
                # 解析章节列表
                soup = BeautifulSoup(html_content, 'html.parser')
                chapter_links = []
                
                # 提取小说ID
                novel_id = None
                pattern = r'/look/(\d+)/'
                match = re.search(pattern, url)
                if match:
                    novel_id = match.group(1)
                    logger.info(f"提取到小说ID: {novel_id}")
                
                # 解析章节列表
                # 查找所有可能的章节链接
                for a_tag in soup.select('a[href*=".html"]'):
                    href = a_tag.get('href', '')
                    title = a_tag.text.strip()
                    # 过滤章节链接（通常包含数字和.html）
                    if href and title and re.search(r'/\d+\.html$', href):
                        chapter_num_match = re.search(r'/(\d+)\.html$', href)
                        if chapter_num_match:
                            chapter_num = int(chapter_num_match.group(1))
                            chapter_links.append({
                                "index": chapter_num,
                                "url": href if href.startswith('http') else urljoin(url, href),
                                "title": title
                            })
                
                # 排序章节链接
                chapter_links.sort(key=lambda x: x["index"])
                
                # 输出章节数量和范围
                if chapter_links:
                    min_chapter = min([c["index"] for c in chapter_links])
                    max_chapter = max([c["index"] for c in chapter_links])
                    
                    logger.info(f"解析到 {len(chapter_links)} 个章节链接")
                    logger.info(f"章节范围: {min_chapter} - {max_chapter}")
                    
                    # 显示前5个和后5个章节
                    if len(chapter_links) > 0:
                        logger.info("前5个章节:")
                        for i, chapter in enumerate(chapter_links[:5]):
                            logger.info(f"  {i+1}. 第{chapter['index']}章: {chapter['title']} - {chapter['url']}")
                            
                    if len(chapter_links) > 5:
                        logger.info("后5个章节:")
                        for i, chapter in enumerate(chapter_links[-5:]):
                            logger.info(f"  {len(chapter_links)-5+i+1}. 第{chapter['index']}章: {chapter['title']} - {chapter['url']}")
                    
                    # 验证最后一章的URL
                    if max_chapter > 0:
                        last_url = None
                        for chapter in chapter_links:
                            if chapter["index"] == max_chapter:
                                last_url = chapter["url"]
                                break
                                
                        if last_url:
                            logger.info(f"最后一章URL: {last_url}")
                            
                            # 访问最后一章URL
                            await crawler.page.goto(last_url, timeout=15000)
                            title = await crawler.page.title()
                            logger.info(f"最后一章页面标题: {title}")
                            
                            # 简单检查内容是否有效
                            content = await crawler.page.content()
                            if "404" in content or "找不到" in content or "不存在" in content:
                                logger.error(f"最后一章可能无效，页面显示错误信息")
                            else:
                                # 解析章节内容
                                soup_content = BeautifulSoup(content, 'html.parser')
                                content_div = soup_content.select_one('#chaptercontent, .content, .chapter-content')
                                if content_div:
                                    text_content = content_div.get_text(strip=True)
                                    logger.info(f"章节内容长度: {len(text_content)} 字符")
                                    logger.info(f"章节内容前100字: {text_content[:100]}...")
                                    logger.info(f"最后一章验证成功")
                                else:
                                    logger.warning(f"未能找到章节内容元素")
                        else:
                            logger.warning(f"未找到最后一章的URL")
                else:
                    logger.warning(f"未解析到任何章节链接")
                    
            except Exception as e:
                logger.error(f"测试URL {url} 时出错: {e}")
                import traceback
                logger.error(traceback.format_exc())
                
            logger.info(f"----- 测试URL: {url} 完成 -----\n")
    
    finally:
        # 关闭浏览器
        await crawler.close_browser()
        
        # 关闭数据库连接
        crawler.db.close()

if __name__ == "__main__":
    asyncio.run(test_chapter_list_parsing()) 