import sys
import os
import logging
import asyncio
from apify_client import ApifyClientAsync
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# 直接写死token
APIFY_TOKEN = "apify_api_gXcR5utLXbObk3xaDgzFeZSfUiQ8Nv3oV5P6"
ACTOR_ID = "ChNuXurElMWvpbJB9"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ApifyCloudflareScraper:
    def __init__(self):
        self.client = ApifyClientAsync(APIFY_TOKEN)
        self.actor_id = ACTOR_ID

    async def scrape(self, url):
        """使用 Apify Cloudflare Web Scraper 爬取网页"""
        try:
            run_input = {
                "execute_js_async": False,
                "js_script": "return 10 + 10 + 20",
                "js_timeout": 10,
                "max_retries_per_url": 2,
                "page_is_loaded_before_running_script": True,
                "proxy": {
                    "useApifyProxy": False
                },
                "retrieve_html_from_url_after_loaded": True,
                "retrieve_result_from_js_script": True,
                "urls": [url]
            }
            logger.info(f"开始运行 Apify Cloudflare Web Scraper 爬取: {url}")
            actor_client = self.client.actor(self.actor_id)
            run = await actor_client.call(run_input=run_input)
            if run is None:
                logger.error("Actor run failed.")
                return None

            dataset_client = self.client.dataset(run["defaultDatasetId"])
            items_result = await dataset_client.list_items()
            items = items_result.items
            if not items:
                logger.error("未获取到任何数据")
                return None

            html_content = items[0].get("html", "")
            if not html_content:
                logger.error("HTML 内容为空")
                return None

            return html_content

        except Exception as e:
            logger.error(f"爬取过程中发生错误: {e}")
            return None

    def parse_chapters(self, html_content, base_url):
        """解析章节列表"""
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            chapter_list = []
            # 只用真实的选择器
            chapter_elements = soup.select('#dir dd a')
            if not chapter_elements:
                logger.error("未找到章节列表元素")
                return []
            for chapter in chapter_elements:
                chapter_url = urljoin(base_url, chapter.get('href'))
                chapter_title = chapter.text.strip()
                chapter_list.append({
                    'title': chapter_title,
                    'url': chapter_url
                })
            return chapter_list
        except Exception as e:
            logger.error(f"解析章节列表时发生错误: {e}")
            return []

    def parse_chapter_content(self, html_content):
        """解析章节详情页内容，提取标题和正文"""
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            # 章节标题
            title_elem = soup.select_one('#ctitle .title, h2.h2, h2')
            title = title_elem.text.strip() if title_elem else ''
            # 章节正文
            content_elem = soup.select_one('#content')
            if content_elem:
                # 提取所有文本内容，去除多余空白
                paragraphs = [p.get_text(strip=True) for p in content_elem.find_all('div', recursive=False)]
                if not paragraphs:
                    # 有些站点正文直接在content下
                    paragraphs = [content_elem.get_text(strip=True)]
                content = '\n'.join(paragraphs)
            else:
                content = ''
            return {
                'title': title,
                'content': content
            }
        except Exception as e:
            logger.error(f"解析章节内容时发生错误: {e}")
            return {'title': '', 'content': ''}

async def test_apify_complete_process():
    """测试完整的小说爬取流程：获取章节列表和多个章节内容"""
    novel_url = "https://www.hetushu.com/book/387/index.html"
    scraper = ApifyCloudflareScraper()
    
    # 1. 首先获取章节列表
    try:
        logger.info("第1步: 获取小说章节列表")
        html_content = await scraper.scrape(novel_url)
        if not html_content:
            logger.error("获取章节列表失败")
            return
            
        chapters = scraper.parse_chapters(html_content, novel_url)
        logger.info(f"成功获取到 {len(chapters)} 个章节")
        
        if not chapters:
            logger.error("未能获取到章节列表")
            return
            
        # 展示前5个章节
        logger.info("章节列表示例(前5章):")
        for i, chapter in enumerate(chapters[:5]):
            logger.info(f"{i+1}. {chapter['title']} - {chapter['url']}")
        
        # 2. 选择前3个章节获取内容
        max_chapters = min(3, len(chapters))
        logger.info(f"\n第2步: 获取前 {max_chapters} 个章节的内容")
        
        for i in range(max_chapters):
            chapter = chapters[i]
            logger.info(f"\n开始获取第 {i+1} 章: {chapter['title']}")
            
            # 获取章节内容
            chapter_content_html = await scraper.scrape(chapter['url'])
            if not chapter_content_html:
                logger.error(f"获取章节 {i+1} 内容失败")
                continue
                
            # 解析章节内容
            result = scraper.parse_chapter_content(chapter_content_html)
            logger.info(f"章节标题: {result['title']}")
            
            # 显示前200字节内容
            content_preview = result['content'][:200] + "..." if len(result['content']) > 200 else result['content']
            logger.info(f"章节内容预览:\n{content_preview}")
            
            # 简单验证
            assert result['title'], "未能提取到章节标题"
            assert result['content'], "未能提取到章节内容"
            
            # 将文件保存到测试目录
            os.makedirs("test_output", exist_ok=True)
            filename = f"test_output/章节{i+1}-{result['title']}.txt"
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(result['content'])
                logger.info(f"章节内容已保存到: {filename}")
            except Exception as e:
                logger.error(f"保存章节内容到文件失败: {e}")
        
        logger.info("\n测试完成!")
    except Exception as e:
        logger.error(f"测试过程中发生错误: {e}")

async def test_apify_scraper():
    url = "https://www.hetushu.com/book/387/index.html"
    scraper = ApifyCloudflareScraper()
    try:
        html_content = await scraper.scrape(url)
        if not html_content:
            logger.error("爬取失败")
            return
        chapters = scraper.parse_chapters(html_content, url)
        logger.info(f"成功获取到 {len(chapters)} 个章节")
        if chapters:
            logger.info("前5个章节:")
            for i, chapter in enumerate(chapters[:5]):
                logger.info(f"{i+1}. {chapter['title']} - {chapter['url']}")
    except Exception as e:
        logger.error(f"测试过程中发生错误: {e}")

async def test_apify_chapter_content():
    """测试通过apify抓取章节详情页并解析正文"""
    url = "https://www.hetushu.com/book/387/221223.html"
    scraper = ApifyCloudflareScraper()
    try:
        html_content = await scraper.scrape(url)
        if not html_content:
            logger.error("章节详情页爬取失败")
            return
        result = scraper.parse_chapter_content(html_content)
        logger.info(f"章节标题: {result['title']}")
        logger.info(f"正文内容前200字: {result['content'][:200]}")
        assert result['title'], "未能提取到章节标题"
        assert result['content'], "未能提取到章节正文"
        logger.info("章节内容解析测试通过！")
    except Exception as e:
        logger.error(f"章节内容测试过程中发生错误: {e}")

if __name__ == "__main__":
    # asyncio.run(test_apify_scraper())
    # asyncio.run(test_apify_chapter_content())
    asyncio.run(test_apify_complete_process()) 