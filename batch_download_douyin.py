#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
抖音视频批量下载工具

用法:
    python batch_download_douyin.py urls.txt
"""

import os
import sys
import time
import logging
from douyin_spider.douyin_spider_client import DouyinSpiderClient

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/batch_download.log')
    ]
)
logger = logging.getLogger('batch_downloader')

def extract_video_id(url):
    """从URL中提取视频ID"""
    if 'modal_id=' in url:
        parts = url.split('modal_id=')
        if len(parts) > 1:
            video_id = parts[1].split('&')[0]
            return video_id
    return None

def batch_download(urls, delay=3):
    """批量下载多个抖音视频
    
    Args:
        urls: 包含多个URL的列表
        delay: 每个请求之间的延迟（秒）
    """
    client = DouyinSpiderClient()
    
    total = len(urls)
    success = 0
    failed = 0
    
    logger.info(f"开始批量下载 {total} 个视频...")
    
    for i, url in enumerate(urls):
        url = url.strip()
        if not url:
            continue
            
        try:
            video_id = extract_video_id(url)
            if video_id:
                logger.info(f"[{i+1}/{total}] 正在处理视频ID: {video_id}")
                
                # 尝试下载视频
                result = client.process_url(url)
                
                if result:
                    success += 1
                    logger.info(f"[{i+1}/{total}] 下载成功: {video_id}")
                else:
                    failed += 1
                    logger.error(f"[{i+1}/{total}] 下载失败: {video_id}")
            else:
                logger.warning(f"[{i+1}/{total}] 无法从URL提取视频ID: {url}")
                failed += 1
                
        except Exception as e:
            logger.error(f"[{i+1}/{total}] 处理出错: {str(e)}")
            failed += 1
            
        # 防止请求过于频繁
        if i < total - 1:
            logger.info(f"等待 {delay} 秒后继续下载...")
            time.sleep(delay)
    
    logger.info(f"批量下载完成: 总计 {total} 个视频, 成功 {success} 个, 失败 {failed} 个")
    return success, failed

def save_urls_to_file(urls, filename='douyin_urls.txt'):
    """将URL列表保存到文件"""
    with open(filename, 'w', encoding='utf-8') as f:
        for url in urls:
            f.write(url.strip() + '\n')
    logger.info(f"已将 {len(urls)} 个URL保存到文件: {filename}")

def main():
    """主函数"""
    if len(sys.argv) > 1:
        # 如果提供了文件名，从文件读取URL
        filename = sys.argv[1]
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                urls = [line.strip() for line in f if line.strip()]
            
            batch_download(urls)
        else:
            print(f"文件不存在: {filename}")
    else:
        # 否则，在控制台等待输入多个URL（一行一个）
        print("请输入抖音URL（每行一个，输入空行结束）:")
        urls = []
        while True:
            line = input()
            if not line:
                break
            urls.append(line.strip())
        
        if urls:
            # 保存URL到文件
            save_urls_to_file(urls)
            # 批量下载
            batch_download(urls)
        else:
            print("未提供任何URL")

if __name__ == "__main__":
    main() 