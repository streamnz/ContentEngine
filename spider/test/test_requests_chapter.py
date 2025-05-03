import asyncio
import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from playwright.async_api import async_playwright

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_hetushu_chapter_list():
    """测试通过 Playwright 获取和解析章节列表"""
    url = "https://www.hetushu.com/book/387/index.html"
    
    try:
        logger.info(f"正在请求: {url}")
        async with async_playwright() as p:
            # 启动浏览器
            browser = await p.firefox.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            
            # 访问页面并等待加载
            await page.goto(url, wait_until="networkidle")
            # 等待一下确保 Cloudflare 检查完成
            await page.wait_for_timeout(5000)
            
            # 获取页面内容
            content = await page.content()
            
            # 解析 HTML
            soup = BeautifulSoup(content, 'html.parser')
            
            # 查找章节列表
            chapter_list = []
            chapter_elements = soup.select('#list dd a')  # 调整选择器
            
            if not chapter_elements:
                logger.warning("未找到章节列表元素，尝试其他选择器...")
                chapter_elements = soup.select('.novel_list a')
            
            # 提取章节信息
            for chapter in chapter_elements:
                chapter_url = urljoin(url, chapter.get('href'))
                chapter_title = chapter.text.strip()
                chapter_list.append({
                    'title': chapter_title,
                    'url': chapter_url
                })
            
            # 输出结果
            logger.info(f"成功获取到 {len(chapter_list)} 个章节")
            if chapter_list:
                logger.info("前5个章节:")
                for i, chapter in enumerate(chapter_list[:5]):
                    logger.info(f"{i+1}. {chapter['title']} - {chapter['url']}")
            
            # 验证结果
            assert len(chapter_list) > 0, "未找到任何章节"
            assert all(chapter['title'] for chapter in chapter_list), "存在空标题的章节"
            assert all(chapter['url'] for chapter in chapter_list), "存在空URL的章节"
            
            logger.info("测试通过！")
            
            # 关闭浏览器
            await browser.close()
            return chapter_list
            
    except Exception as e:
        logger.error(f"测试失败: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(test_hetushu_chapter_list()) 