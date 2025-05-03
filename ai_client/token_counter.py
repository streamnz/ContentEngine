import re
import json
import openai
import anthropic
from config import DEEPSEEK_CONFIG, CLAUDE_CONFIG

# 添加模型限制信息常量
CLAUDE_LIMITS = {
    'claude-3-5-sonnet-20241022': {
        'input_tokens_per_minute': 40000,
        'output_tokens_per_minute': 8000,
        'max_input_tokens': 200000,
        'max_output_tokens': 4096
    },
    'claude-3-5-sonnet-20240620': {
        'input_tokens_per_minute': 40000,
        'output_tokens_per_minute': 8000,
        'max_input_tokens': 200000,
        'max_output_tokens': 4096
    },
    'claude-3-5-haiku': {
        'input_tokens_per_minute': 50000,
        'output_tokens_per_minute': 10000,
        'max_input_tokens': 200000,
        'max_output_tokens': 4096,
        'price_input': 1.5,  # 每百万token价格（元）
        'price_output': 4.5  # 每百万token价格（元）
    },
    'claude-3-haiku': {
        'input_tokens_per_minute': 50000,
        'output_tokens_per_minute': 10000,
        'max_input_tokens': 200000,
        'max_output_tokens': 4096
    },
    'claude-3-opus': {
        'input_tokens_per_minute': 20000,
        'output_tokens_per_minute': 4000,
        'max_input_tokens': 200000,
        'max_output_tokens': 4096
    }
}

DEEPSEEK_LIMITS = {
    'deepseek-chat': {
        'max_input_tokens': 64000,
        'max_output_tokens': 8000
    }
}

def count_tokens_estimate(text):
    """估算文本的token数量"""
    # 分离HTML标签和文本内容
    html_tags = re.findall(r'<[^>]+>', text)
    text_content = re.sub(r'<[^>]+>', '', text)
    
    # 计算HTML标签的tokens (大约4个字符1个token)
    html_tokens = sum(len(tag) for tag in html_tags) // 4
    
    # 计算中文字符数
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text_content))
    
    # 计算非中文字符数
    non_chinese_chars = len(re.sub(r'[\u4e00-\u9fff]', '', text_content))
    
    # 中文字符 * 2 + 非中文字符 / 4
    text_tokens = chinese_chars * 2 + non_chinese_chars // 4
    
    return html_tokens + text_tokens

def count_tokens_deepseek(text):
    """使用DeepSeek API获取准确的token数量"""
    client = openai.OpenAI(
        api_key=DEEPSEEK_CONFIG['api_key'],
        base_url=DEEPSEEK_CONFIG['base_url']
    )
    
    # 调用API获取token数量
    response = client.chat.completions.create(
        model=DEEPSEEK_CONFIG['model'],
        messages=[{"role": "user", "content": text}],
        max_tokens=1,  # 只需要计算输入tokens
    )
    
    return response.usage.prompt_tokens

def count_tokens_claude(text):
    """使用Claude API获取准确的token数量"""
    client = anthropic.Anthropic(
        api_key=CLAUDE_CONFIG['api_key']
    )
    
    # 使用Claude API的count_tokens方法
    token_count = client.count_tokens(text)
    
    return token_count

def analyze_token_usage(html_file):
    """分析HTML文件的token用量并比较Claude和DeepSeek"""
    # 读取HTML文件
    with open(html_file, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    # 文件大小
    file_size_bytes = len(html_content.encode('utf-8'))
    file_size_kb = file_size_bytes / 1024
    
    print(f"文件大小: {file_size_kb:.2f} KB ({file_size_bytes} bytes)")
    
    # 估算token数量
    estimated_tokens = count_tokens_estimate(html_content)
    print(f"估算的token数量: {estimated_tokens}")
    
    # 使用DeepSeek API计算
    try:
        deepseek_tokens = count_tokens_deepseek(html_content)
        print(f"DeepSeek的token数量: {deepseek_tokens}")
        deepseek_capacity = DEEPSEEK_LIMITS['deepseek-chat']['max_input_tokens']
        deepseek_percentage = (deepseek_tokens / deepseek_capacity) * 100
        print(f"DeepSeek容量使用率: {deepseek_percentage:.2f}% (最大容量: {deepseek_capacity})")
    except Exception as e:
        print(f"DeepSeek token计算失败: {str(e)}")
    
    # 使用Claude API计算
    try:
        claude_tokens = count_tokens_claude(html_content)
        print(f"Claude的token数量: {claude_tokens}")
        
        # 获取当前使用的Claude模型信息
        current_model = CLAUDE_CONFIG['model']
        model_key = current_model if current_model in CLAUDE_LIMITS else 'claude-3-5-sonnet-20241022'
        
        claude_capacity = CLAUDE_LIMITS[model_key]['max_input_tokens']
        claude_percentage = (claude_tokens / claude_capacity) * 100
        print(f"Claude容量使用率: {claude_percentage:.2f}% (最大容量: {claude_capacity})")
        print(f"Claude每分钟输入token限制: {CLAUDE_LIMITS[model_key]['input_tokens_per_minute']}")
        print(f"Claude每分钟输出token限制: {CLAUDE_LIMITS[model_key]['output_tokens_per_minute']}")
    except Exception as e:
        print(f"Claude token计算失败: {str(e)}")
    
    # 构建基本提示词框架估算token用量
    deepseek_prompt_template = """作为网页分析专家，请分析以下HTML内容并以JSON格式返回分析结果。要求：精确、可靠、保持一致性。

任务要求：
1. 页面类型判断
2. 信息提取
3. 下一步指示

请以JSON格式返回"""

    claude_prompt_template = """作为网页分析专家，你的任务是提取这个HTML页面中的所有小说章节列表信息，不遗漏任何章节。

请分析下面的小说网站HTML，并提取以下信息：
1. 小说标题
2. 作者名
3. 小说简介
4. 所有章节的标题和URL
5. 小说分类

直接以JSON格式响应，不要添加任何前言或解释。"""

    deepseek_prompt_tokens = count_tokens_estimate(deepseek_prompt_template)
    claude_prompt_tokens = count_tokens_estimate(claude_prompt_template)
    
    print(f"\n提示词框架token估算:")
    print(f"DeepSeek提示词框架: ~{deepseek_prompt_tokens} tokens")
    print(f"Claude提示词框架: ~{claude_prompt_tokens} tokens")
    
    total_deepseek = deepseek_prompt_tokens + deepseek_tokens
    total_claude = claude_prompt_tokens + claude_tokens
    
    print(f"\n总计token使用估算:")
    print(f"DeepSeek总计: ~{total_deepseek} tokens (最大: {DEEPSEEK_LIMITS['deepseek-chat']['max_input_tokens']})")
    print(f"Claude总计: ~{total_claude} tokens (最大: {CLAUDE_LIMITS[model_key]['max_input_tokens']})")
    
    # 分析结果
    print("\n结论:")
    print(f"1. HTML内容可能需要 {deepseek_tokens} 到 {claude_tokens} tokens")
    print(f"2. 加上提示词框架，总token使用量为 {total_deepseek} 到 {total_claude} tokens")
    
    # 如果要解析200个章节需要多少tokens的分析
    avg_chapter_tokens = 30  # 假设每个章节条目平均30 tokens
    chapters_200_tokens = avg_chapter_tokens * 200
    print(f"\n如果提取200个章节:")
    print(f"估计章节列表部分需要: ~{chapters_200_tokens} tokens")
    print(f"DeepSeek总需求: ~{total_deepseek + chapters_200_tokens - 300} tokens") # 假设当前已有10章节，减去300tokens
    print(f"Claude总需求: ~{total_claude + chapters_200_tokens - 300} tokens")
    
    # 添加API费用估算
    print("\nAPI费用估算:")
    # DeepSeek费用 (标准时段)
    deepseek_input_cost = (total_deepseek / 1000000) * 2  # 2元/百万tokens
    deepseek_output_cost = (8000 / 1000000) * 8  # 8元/百万tokens，假设8K输出
    print(f"DeepSeek API费用: 输入约 {deepseek_input_cost:.6f}元, 输出约 {deepseek_output_cost:.6f}元")
    
    # Claude费用 (假设标准费率)
    claude_input_cost = (total_claude / 1000000) * 15  # 假设15元/百万tokens
    claude_output_cost = (8000 / 1000000) * 45  # 假设45元/百万tokens，8K输出
    print(f"Claude API费用: 输入约 {claude_input_cost:.6f}元, 输出约 {claude_output_cost:.6f}元")

if __name__ == "__main__":
    # 分析HTML文件
    analyze_token_usage('latest_page.html') 