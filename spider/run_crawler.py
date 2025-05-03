import asyncio
import argparse
import logging
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawler import NovelCrawler
from config import CRAWLER_CONFIG

def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='小说爬虫工具')
    
    # 必选参数
    parser.add_argument('--url', type=str, default=CRAWLER_CONFIG['base_url'],
                        help='要爬取的小说URL，默认使用配置中的URL')
    
    # 可选参数
    parser.add_argument('--limit', type=int, default=1,
                        help='要爬取的章节数量，设置为0表示爬取全部章节')
    parser.add_argument('--parallel', type=int, default=3,
                        help='并行爬取的章节数量，设置为1表示禁用并行爬取')
    parser.add_argument('--headless', action='store_true',
                        help='是否使用无头模式运行浏览器')
    parser.add_argument('--timeout', type=int, default=30000,
                        help='页面加载超时时间(毫秒)')
    parser.add_argument('--skip-images', action='store_true', default=True,
                        help='是否跳过图片加载')
    parser.add_argument('--block-ads', action='store_true', default=True,
                        help='是否阻止广告脚本')
    parser.add_argument('--log-level', type=str, choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], 
                        default='INFO', help='日志级别：DEBUG(调试)/INFO(信息)/WARNING(警告)/ERROR(错误)')
    parser.add_argument('--quiet', action='store_true',
                        help='安静模式，只输出错误信息')
    parser.add_argument('--use-apify', action='store_true', default=CRAWLER_CONFIG.get('use_apify', False),
                        help='是否使用Apify爬取网页内容，默认根据配置文件设置')
    parser.add_argument('--no-apify', action='store_true', 
                        help='禁用Apify，强制使用Playwright爬取')
    
    return parser.parse_args()

def set_log_level(level_name, quiet=False):
    """设置日志级别"""
    # 转换日志级别字符串为logging模块的常量
    level_map = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR
    }
    log_level = level_map.get(level_name, logging.INFO)
    
    # 如果是安静模式，覆盖为WARNING级别
    if quiet:
        log_level = logging.WARNING
    
    # 设置根日志记录器级别
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # 设置各个子日志记录器级别
    loggers = [
        logging.getLogger('crawler'),
        logging.getLogger('network'),
        logging.getLogger('parser'),
        logging.getLogger('database'),
        logging.getLogger('ai')
    ]
    
    for logger in loggers:
        logger.setLevel(log_level)
    
    print(f"[设置] 日志级别: {level_name}" + (" (安静模式)" if quiet else ""))

async def main():
    # 解析命令行参数
    args = parse_arguments()
    
    # 设置日志级别
    set_log_level(args.log_level, args.quiet)
    
    # 实例化爬虫
    print("[Python] [初始化] 创建爬虫实例")
    crawler = NovelCrawler()
    
    # 设置性能参数
    print("[Python] [配置] 设置爬虫参数")
    crawler.parallel_chapters = args.parallel
    crawler.page_timeout = args.timeout
    crawler.skip_images = args.skip_images
    crawler.enable_js_blocking = args.block_ads
    
    # 设置是否使用Apify
    if args.no_apify:
        crawler.use_apify = False
        print("[Python] [配置] 禁用Apify，使用Playwright爬取")
    elif args.use_apify:
        crawler.use_apify = True
        crawler.enable_apify()  # 确保Apify客户端被初始化
        print("[Python] [配置] 启用Apify爬取")
    
    # 设置要爬取的小说URL
    novel_url = args.url
    
    # 设置爬取章节数量限制
    limit_chapters = None if args.limit == 0 else args.limit
    
    try:
        # 开始爬取
        print(f"[Shell] [运行] 开始爬取小说: {novel_url}")
        print(f"[Shell] [运行] 限制章节数: {limit_chapters if limit_chapters else '无限制'}")
        print(f"[Shell] [运行] 并行爬取: {'启用' if args.parallel > 1 else '禁用'}, 并行数: {args.parallel}")
        print(f"[Shell] [运行] 无头模式: {'启用' if args.headless else '禁用'}")
        print(f"[Shell] [运行] 页面超时: {args.timeout}ms")
        print(f"[Shell] [运行] 跳过图片: {'是' if args.skip_images else '否'}")
        print(f"[Shell] [运行] 阻止广告: {'是' if args.block_ads else '否'}")
        print(f"[Shell] [运行] 使用Apify: {'是' if crawler.use_apify else '否'}")
        
        await crawler.crawl_novel(novel_url, limit_chapters)
    except Exception as e:
        print(f"[Python] [错误] 爬取过程中发生错误: {e}")
    
    print("[Shell] [运行] 爬虫任务已完成")

if __name__ == "__main__":
    asyncio.run(main()) 