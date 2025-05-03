from playwright.async_api import async_playwright
import asyncio

async def save_page_html():
    async with async_playwright() as p:
        browser = await p.firefox.launch()
        page = await browser.new_page()
        
        # 访问目标页面
        await page.goto('https://www.bqgl.cc/look/52359/')
        
        # 等待页面加载
        await page.wait_for_load_state('networkidle')
        
        # 获取页面内容
        content = await page.content()
        
        # 保存到文件
        with open('latest_page.html', 'w', encoding='utf-8') as f:
            f.write(content)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(save_page_html()) 