#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
抖音视频下载工具

用法:
    python download_douyin.py [抖音视频URL]        - 下载单个视频
    python download_douyin.py --process-pending    - 处理所有待下载视频
    python download_douyin.py --process-pending 5  - 处理指定数量的待下载视频
    python download_douyin.py --add-url [URL]      - 仅添加URL到数据库，不立即下载
    python download_douyin.py --transcribe [ID]    - 仅对指定ID的视频进行音频转写
    python download_douyin.py --process-text [ID]  - 仅对指定ID的视频进行文本润色和小说识别

示例:
    python download_douyin.py https://www.douyin.com/video/7045159024525905183
    python download_douyin.py --process-pending 10
    python download_douyin.py --transcribe 7496842121786314035
    python download_douyin.py --process-text 7496842121786314035
"""

import sys
import logging
import os
from douyin_spider_client import DouyinSpiderClient
from database.database import Database

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('douyin_downloader')

def show_help():
    """显示帮助信息"""
    print(__doc__)

def add_url_to_database(url):
    """将URL添加到数据库，不进行下载"""
    try:
        db = Database()
        video_id = db.insert_douyin_video(source_url=url)
        if video_id:
            print(f"已将视频URL添加到下载队列: {url}")
            print(f"记录ID: {video_id}，状态: pending")
        else:
            print(f"无法将视频URL添加到下载队列: {url}")
    except Exception as e:
        print(f"错误: {str(e)}")

def transcribe_audio(douyin_id):
    """仅对指定ID的视频进行音频转写"""
    try:
        client = DouyinSpiderClient()
        db = Database()
        
        # 获取视频信息
        video = db.get_douyin_video_by_id(douyin_id)
        if not video:
            print(f"未找到抖音ID为 {douyin_id} 的视频")
            return False
        
        # 检查音频文件是否存在
        audio_path = video[11]  # audio_path列
        if not audio_path or not os.path.exists(audio_path):
            print(f"未找到音频文件或文件不存在: {audio_path}")
            return False
        
        print(f"找到音频文件: {audio_path}")
        
        # 转写音频
        print("开始音频转写，请稍候...")
        text = client.transcribe_audio(audio_path)
        if not text:
            print("音频转写失败")
            return False
        
        # 保存到文本文件
        txt_path = os.path.splitext(audio_path)[0] + ".txt"
        if client.save_text_to_file(text, txt_path):
            print(f"文本保存成功: {txt_path}")
        
        # 更新数据库
        db.update_douyin_video_status(douyin_id, status=video[14], audio_text=text)
        print("数据库记录已更新")
        
        # 显示部分文本预览
        preview_length = min(300, len(text))
        print(f"\n文本预览（前{preview_length}字符）:")
        print("=" * 40)
        print(text[:preview_length] + ("..." if len(text) > preview_length else ""))
        print("=" * 40)
        
        return True
        
    except Exception as e:
        print(f"错误: {str(e)}")
        return False

def process_text(douyin_id):
    """仅对指定ID的视频进行文本润色和小说识别"""
    try:
        client = DouyinSpiderClient()
        db = Database()
        
        # 获取视频信息
        video = db.get_douyin_video_by_id(douyin_id)
        if not video:
            print(f"未找到抖音ID为 {douyin_id} 的视频")
            return False
        
        # 检查是否已有音频转写文本
        audio_text = video[13]  # audio_text列
        if not audio_text:
            print(f"视频 {douyin_id} 没有音频转写文本，请先进行音频转写")
            return False
        
        video_id = video[0]  # 数据库ID
        
        # 处理文本
        print(f"开始处理视频 {douyin_id} 的音频文本...")
        result = client.text_processor.process_audio_text(douyin_id, audio_text, video_id)
        
        if not result:
            print("文本处理失败")
            return False
            
        # 显示处理结果
        novel_name = result.get("novel_name", "未知")
        novel_id = result.get("novel_id")
        confidence = result.get("confidence", 0)
        summary = result.get("summary", "")
        polished_text = result.get("polished_text", "")
        
        print("\n处理完成!")
        print("=" * 40)
        if novel_name and novel_name != "未知":
            print(f"识别到相关小说: {novel_name} (ID: {novel_id}, 置信度: {confidence:.2f})")
        else:
            print("未识别到相关小说")
            
        print("\n内容总结:")
        print(summary)
        
        # 显示润色后的文本预览
        print("\n润色后的文本预览（前300字符）:")
        preview_length = min(300, len(polished_text))
        print("=" * 40)
        print(polished_text[:preview_length] + ("..." if len(polished_text) > preview_length else ""))
        print("=" * 40)
        
        # 保存润色后的文本到文件
        if video[11]:  # audio_dir
            processed_text_path = os.path.join(os.path.dirname(video[11]), f"{douyin_id}_processed.txt")
            client.save_text_to_file(polished_text, processed_text_path)
            print(f"\n润色后的文本已保存至: {processed_text_path}")
        
        return True
        
    except Exception as e:
        print(f"错误: {str(e)}")
        return False

def main():
    """主函数"""
    if len(sys.argv) < 2:
        show_help()
        return
    
    try:
        # 处理命令行参数
        if sys.argv[1] in ['--help', '-h']:
            show_help()
            return
            
        if sys.argv[1] == '--add-url':
            # 仅添加URL到数据库
            if len(sys.argv) < 3:
                print("错误: 缺少URL参数")
                return
            add_url_to_database(sys.argv[2])
            return
            
        if sys.argv[1] == '--transcribe':
            # 仅对指定ID的视频进行音频转写
            if len(sys.argv) < 3:
                print("错误: 缺少抖音ID参数")
                return
            transcribe_audio(sys.argv[2])
            return
            
        if sys.argv[1] == '--process-text':
            # 仅对指定ID的视频进行文本润色和小说识别
            if len(sys.argv) < 3:
                print("错误: 缺少抖音ID参数")
                return
            process_text(sys.argv[2])
            return
            
        # 初始化爬虫客户端
        client = DouyinSpiderClient()
        
        if sys.argv[1] == '--process-pending':
            # 处理待下载队列
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
            print(f"开始处理队列中的{limit}个视频...")
            count = client.process_pending_videos(limit=limit)
            print(f"批量处理完成，共处理 {count} 个视频")
        else:
            # 将第一个参数作为URL处理
            url = sys.argv[1]
            print(f"开始下载视频: {url}")
            result = client.process_url(url)
            
            if result:
                print(f"视频下载成功: {url}")
            else:
                print(f"视频下载失败: {url}")
                
    except KeyboardInterrupt:
        print("\n操作已取消")
    except Exception as e:
        print(f"错误: {str(e)}")

if __name__ == "__main__":
    main() 