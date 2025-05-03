import os
from dotenv import load_dotenv

# 强制加载.env文件
load_dotenv(verbose=True)

import asyncio
import logging
import json
import re
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from ai_client.claude_client import ClaudeClient
from ai_client.deepseek_client import DeepSeekClient
import anthropic
from openai import OpenAI
from config import DEEPSEEK_CONFIG, CLAUDE_CONFIG
import argparse

# 调试输出加载的环境变量
print(f"DEEPSEEK_API_KEY: {os.getenv('DEEPSEEK_API_KEY')[:8]}***")
print(f"ANTHROPIC_API_KEY: {os.getenv('ANTHROPIC_API_KEY')[:8]}***")

# 仅设置非敏感配置
DEEPSEEK_CONFIG['base_url'] = 'https://api.deepseek.com/v1'  # 确保base_url正确
DEEPSEEK_CONFIG['model'] = 'deepseek-chat'  # 使用deepseek-chat模型
DEEPSEEK_CONFIG['response_format'] = None  # 不强制返回JSON格式
DEEPSEEK_CONFIG['max_output_tokens'] = 8000  # 设置最大输出token
CLAUDE_CONFIG['model'] = 'claude-3-7-sonnet-20250219'  # 使用Claude 3.7 Sonnet模型
CLAUDE_CONFIG['max_output_tokens'] = 64000  # 设置最大输出token

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('test_models.log', encoding='utf-8')
    ]
)

# 添加分隔符辅助函数，使日志输出更清晰
def log_separator(title=""):
    if title:
        separator = f"===== {title} ====="
    else:
        separator = "=" * 50
    logging.info(separator)

def extract_chapters_from_html(html):
    """使用BeautifulSoup从HTML中提取章节信息"""
    soup = BeautifulSoup(html, 'html.parser')
    result = {
        "title": "",
        "author": "",
        "description": "",
        "chapters": []
    }
    
    # 提取小说标题
    title_elem = soup.select_one('h1, h2, .book-title, .novel-title')
    if title_elem:
        result["title"] = title_elem.text.strip()
    
    # 提取作者
    author_elem = soup.select_one('.book-author, .author, [itemprop="author"]')
    if author_elem:
        result["author"] = author_elem.text.strip().replace('作者：', '').replace('作者:', '')
    
    # 提取描述
    desc_elem = soup.select_one('.book-intro, .intro, .description, [itemprop="description"]')
    if desc_elem:
        result["description"] = desc_elem.text.strip()
    
    # 提取所有章节链接
    chapter_links = set()
    all_links = soup.select('a[href]')
    for link in all_links:
        href = link.get('href', '')
        title = link.text.strip()
        # 识别章节链接的通用模式（包含数字和.html的链接）
        if re.search(r'/\d+\.html$', href) and title and len(title) < 50:
            chapter_links.add((title, href))
    
    # 转换为列表并排序
    sorted_chapters = sorted(list(chapter_links), key=lambda x: x[1])
    for title, url in sorted_chapters:
        result["chapters"].append({
            "title": title,
            "url": url
        })
    
    # 识别可能的展开按钮
    expand_buttons = []
    for button in soup.select('a, button, .more, .show-more, .expand, .allshow'):
        text = button.text.strip().lower()
        if any(keyword in text for keyword in ['展开', '更多', '全部', 'more', 'show', 'expand', 'all']):
            expand_buttons.append({
                "text": button.text.strip(),
                "selector": get_selector(button)
            })
    
    if expand_buttons:
        result["expand_buttons"] = expand_buttons
    
    return result

def get_selector(element):
    """尝试为元素构建简单的CSS选择器"""
    if element.get('id'):
        return f"#{element['id']}"
    elif element.get('class'):
        return f".{' .'.join(element['class'])}"
    else:
        return element.name

async def test_token_usage(html_content):
    """测试两个模型的token使用情况"""
    # 获取Claude token计数 (使用正确的API方法)
    claude_client = anthropic.Anthropic(api_key=CLAUDE_CONFIG['api_key'])
    
    try:
        # 估算Claude tokens (anthropic库的新版本使用不同的方法)
        claude_message = claude_client.messages.create(
            model=CLAUDE_CONFIG['model'],
            max_tokens=1,
            messages=[{"role": "user", "content": html_content}],
            stream=False
        )
        # 从响应中提取token计数 
        claude_tokens = claude_message.usage.input_tokens
    except Exception as e:
        # 如果API调用失败，使用估算方法
        logging.error(f"Claude token计数API调用失败: {str(e)}")
        claude_tokens = len(html_content) // 4  # 粗略估计
    
    # 获取DeepSeek token计数
    deepseek_client = OpenAI(
        api_key=DEEPSEEK_CONFIG['api_key'],
        base_url=DEEPSEEK_CONFIG['base_url']
    )
    
    try:
        deepseek_response = deepseek_client.chat.completions.create(
            model=DEEPSEEK_CONFIG['model'],
            messages=[{"role": "user", "content": html_content}],
            max_tokens=1  # 只计算输入tokens
        )
        deepseek_tokens = deepseek_response.usage.prompt_tokens
    except Exception as e:
        logging.error(f"DeepSeek token计数API调用失败: {str(e)}")
        deepseek_tokens = len(html_content) // 4  # 粗略估计
    
    logging.info(f"HTML内容的token计数对比:")
    logging.info(f"Claude token计数: {claude_tokens}")
    logging.info(f"DeepSeek token计数: {deepseek_tokens}")
    
    return claude_tokens, deepseek_tokens

async def test_chapter_list_extraction():
    """测试Claude和DeepSeek提取章节列表的效果比较"""
    # 初始化客户端
    claude_client = ClaudeClient()
    deepseek_client = DeepSeekClient()
    
    # 测试URL
    url = 'https://www.bqgl.cc/look/52359/'
    
    log_separator("开始测试")
    
    # 初始化浏览器
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        
        # 访问页面
        logging.info(f"正在访问页面: {url}")
        await page.goto(url, timeout=180000)
        
        # 注意：HTML中已包含所有章节，无需点击"展开全部"按钮
        
        # 滚动到底部确保加载所有内容
        logging.info("滚动页面以加载所有内容...")
        for i in range(10):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.5)
        
        # 获取页面内容
        html_content = await page.content()
        html_size = len(html_content)
        logging.info(f"页面内容大小: {html_size} 字节")
        
        # 保存HTML内容到文件（保留这个，因为HTML文件可能用于调试）
        with open('latest_page.html', 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        # 获取页面上显示的章节数量
        visible_chapters_count = await page.evaluate("""() => {
            const chapterLinks = document.querySelectorAll('a[href*=".html"]');
            return chapterLinks.length;
        }""")
        logging.info(f"页面上可见的章节链接数量: {visible_chapters_count}")
        
        log_separator("DOM解析")
        
        # 使用DOM解析提取章节信息
        logging.info("使用DOM解析提取章节信息...")
        extracted_data = extract_chapters_from_html(html_content)
        dom_chapters_count = len(extracted_data["chapters"])
        logging.info(f"DOM解析提取到 {dom_chapters_count} 个章节")
        
        # 打印DOM提取的前10个章节到日志（不再保存到文件）
        logging.info("DOM提取的章节预览（前10章）:")
        for i, chapter in enumerate(extracted_data["chapters"][:10]):
            logging.info(f"  {i+1}. {chapter['title']} - {chapter['url']}")
        if dom_chapters_count > 10:
            logging.info(f"  ... (共 {dom_chapters_count} 章)")
        
        # 测试token使用情况
        claude_tokens, deepseek_tokens = await test_token_usage(html_content)
        
        # 将提取的章节信息转换为文本形式
        chapter_text = "\n".join([f"{i+1}. {chapter['title']} - {chapter['url']}" 
                                   for i, chapter in enumerate(extracted_data["chapters"])])
        
        # 构建结构化数据给模型
        structured_data = f"""网站标题: {extracted_data.get('title', '未知标题')}
作者: {extracted_data.get('author', '未知作者')}
简介: {extracted_data.get('description', '无简介')}

章节列表:
{chapter_text}
"""
        
        log_separator("Claude处理")
        
        # 使用Claude分析提取的章节信息
        logging.info("使用Claude分析提取的章节信息...")
        start_time = asyncio.get_event_loop().time()
        claude_result = claude_client.analyze_structured_data(structured_data, dom_chapters_count)
        claude_time = asyncio.get_event_loop().time() - start_time
        
        # 检查Claude结果
        if claude_result:
            # 尝试从结果中提取章节信息
            claude_chapters = claude_client.parse_chapters_from_response(claude_result)
            claude_chapters_count = len(claude_chapters)
            logging.info(f"Claude成功处理 {claude_chapters_count} 个章节，用时: {claude_time:.2f}秒")
            
            # 打印Claude提取的前10个章节到日志（不再保存到文件）
            logging.info("Claude处理的章节预览（前10章）:")
            for i, chapter in enumerate(claude_chapters[:10]):
                logging.info(f"  {i+1}. {chapter['title']} - {chapter.get('url', 'N/A')}")
            if claude_chapters_count > 10:
                logging.info(f"  ... (共 {claude_chapters_count} 章)")
            
            # 记录Claude完整响应到日志（可选，如果太长可能需要截断）
            logging.info("Claude响应摘要:")
            if len(claude_result) > 500:
                logging.info(f"{claude_result[:500]}...")
            else:
                logging.info(claude_result)
        else:
            logging.error("Claude分析失败")
            claude_chapters_count = 0
        
        log_separator("DeepSeek处理")
        
        # 使用DeepSeek分析提取的章节信息
        logging.info("使用DeepSeek分析提取的章节信息...")
        start_time = asyncio.get_event_loop().time()
        deepseek_result = deepseek_client.analyze_structured_data(structured_data, dom_chapters_count)
        deepseek_time = asyncio.get_event_loop().time() - start_time
        
        # 检查DeepSeek结果
        if deepseek_result:
            # 尝试从结果中提取章节信息
            deepseek_chapters = deepseek_client.parse_chapters_from_response(deepseek_result)
            deepseek_chapters_count = len(deepseek_chapters)
            logging.info(f"DeepSeek成功处理 {deepseek_chapters_count} 个章节，用时: {deepseek_time:.2f}秒")
            
            # 打印DeepSeek提取的前10个章节到日志（不再保存到文件）
            logging.info("DeepSeek处理的章节预览（前10章）:")
            for i, chapter in enumerate(deepseek_chapters[:10]):
                logging.info(f"  {i+1}. {chapter['title']} - {chapter.get('url', 'N/A')}")
            if deepseek_chapters_count > 10:
                logging.info(f"  ... (共 {deepseek_chapters_count} 章)")
            
            # 记录DeepSeek完整响应到日志（可选，如果太长可能需要截断）
            logging.info("DeepSeek响应摘要:")
            if len(deepseek_result) > 500:
                logging.info(f"{deepseek_result[:500]}...")
            else:
                logging.info(deepseek_result)
        else:
            logging.error("DeepSeek分析失败")
            deepseek_chapters_count = 0
        
        log_separator("结果比较")
        
        # 比较结果
        logging.info(f"HTML内容大小: {html_size} 字节")
        logging.info(f"DOM解析提取章节数: {dom_chapters_count}")
        logging.info(f"页面上可见章节链接数: {visible_chapters_count}")
        logging.info(f"最终提取结果: DOM ({dom_chapters_count} 章) vs Claude ({claude_chapters_count} 章) vs DeepSeek ({deepseek_chapters_count} 章)")
        logging.info(f"处理时间: Claude ({claude_time:.2f}秒) vs DeepSeek ({deepseek_time:.2f}秒)")
        
        log_separator("测试完成")
        
        await browser.close()

async def test_string_protocol():
    """测试新的字符串协议处理能力"""
    # 初始化客户端
    claude_client = ClaudeClient()
    deepseek_client = DeepSeekClient()
    
    # 测试数据
    test_data = """
以下是小说章节的示例格式：

<<<CHAPTER_START>>>
标题：第一章 序幕
链接：/look/12345/1.html
<<<CHAPTER_END>>>

<<<CHAPTER_START>>>
标题：第二章 出发
链接：/look/12345/2.html
<<<CHAPTER_END>>>

<<<PROCESSING_COMPLETE>>>
    """
    
    log_separator("字符串协议测试")
    
    # 测试Claude解析
    logging.info("测试Claude解析字符串协议...")
    claude_chapters = claude_client.parse_chapters_from_response(test_data)
    logging.info(f"Claude提取到 {len(claude_chapters)} 个章节")
    for i, chapter in enumerate(claude_chapters):
        logging.info(f"  {i+1}. {chapter['title']} - {chapter.get('url', 'N/A')}")
    
    # 测试DeepSeek解析
    logging.info("测试DeepSeek解析字符串协议...")
    deepseek_chapters = deepseek_client.parse_chapters_from_response(test_data)
    logging.info(f"DeepSeek提取到 {len(deepseek_chapters)} 个章节")
    for i, chapter in enumerate(deepseek_chapters):
        logging.info(f"  {i+1}. {chapter['title']} - {chapter.get('url', 'N/A')}")
    
    # 测试完成标记识别
    is_complete = "<<<PROCESSING_COMPLETE>>>" in test_data
    logging.info(f"处理完成标记检测: {'已完成' if is_complete else '未完成'}")
    
    log_separator("字符串协议测试完成")

async def test_dom_preprocessing():
    """测试DOM预处理功能"""
    log_separator("DOM预处理测试")
    
    # 读取已保存的HTML文件
    try:
        with open('latest_page.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
            logging.info(f"成功读取HTML文件，大小: {len(html_content)} 字节")
    except Exception as e:
        logging.error(f"读取HTML文件失败: {e}")
        # 如果无法读取文件，则使用初始测试URL获取
        logging.info("尝试从URL获取HTML内容...")
        
        # 初始化浏览器并获取页面
        async with async_playwright() as p:
            browser = await p.firefox.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            
            # 访问测试页面
            url = 'https://www.bqgl.cc/look/52359/'
            await page.goto(url, timeout=60000)
            
            # 滚动加载内容
            for i in range(5):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(0.5)
            
            # 获取页面内容
            html_content = await page.content()
            logging.info(f"从URL获取HTML内容，大小: {len(html_content)} 字节")
            
            # 保存HTML到文件
            with open('latest_page.html', 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            await browser.close()
    
    # 使用BeautifulSoup进行DOM预处理
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 提取章节链接
    chapters = []
    all_links = soup.select('a[href]')
    chapter_count = 0
    
    for link in all_links:
        href = link.get('href', '')
        title = link.text.strip()
        # 识别章节链接的通用模式
        if re.search(r'/\d+\.html$', href) and title and len(title) < 50:
            chapters.append({
                "title": title,
                "url": href
            })
            chapter_count += 1
    
    logging.info(f"DOM预处理提取到 {chapter_count} 个章节")
    
    # 格式化为字符串协议格式
    formatted_chapters = ""
    for chapter in chapters[:10]:  # 只展示前10章
        formatted_chapters += f"<<<CHAPTER_START>>>\n"
        formatted_chapters += f"标题：{chapter['title']}\n"
        formatted_chapters += f"链接：{chapter['url']}\n"
        formatted_chapters += f"<<<CHAPTER_END>>>\n\n"
    
    logging.info("DOM预处理后的章节示例(字符串协议格式):")
    logging.info(formatted_chapters[:500] + "..." if len(formatted_chapters) > 500 else formatted_chapters)
    
    # 添加完成标记
    formatted_chapters += "<<<PROCESSING_COMPLETE>>>\n"
    
    log_separator("DOM预处理测试完成")

async def main():
    """主函数，根据命令行参数运行指定测试"""
    parser = argparse.ArgumentParser(description='测试大模型和DOM预处理功能')
    parser.add_argument('--test', choices=['all', 'string', 'dom', 'full'], default='all',
                      help='指定要运行的测试: string(字符串协议测试), dom(DOM预处理测试), full(完整章节提取测试), all(所有测试)')
    
    args = parser.parse_args()
    
    if args.test == 'string' or args.test == 'all':
        log_separator("运行字符串协议测试")
        await test_string_protocol()
    
    if args.test == 'dom' or args.test == 'all':
        log_separator("运行DOM预处理测试")
        await test_dom_preprocessing()
    
    if args.test == 'full' or args.test == 'all':
        log_separator("运行完整章节提取测试")
        await test_chapter_list_extraction()
    
    logging.info("所有测试完成")

if __name__ == "__main__":
    asyncio.run(main()) 