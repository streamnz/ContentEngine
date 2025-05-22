#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
抖音音频转文本测试工具

用法:
    python test_audio_transcribe.py <音频文件路径>
    python test_audio_transcribe.py <douyin_id>  # 从数据库中查找音频文件

示例:
    python test_audio_transcribe.py data/douyin/某视频/audio/123456789.mp3
    python test_audio_transcribe.py 123456789
"""

import os
import sys
import logging
from douyin_spider.douyin_spider_client import DouyinSpiderClient
from database.database import Database
from ai_client.tencent_asr import TencentASRClient

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('audio_transcribe_test')

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    
    # 初始化客户端
    client = DouyinSpiderClient()
    tencent_asr = TencentASRClient()
    path_or_id = sys.argv[1]
    
    # 直接使用文件路径
    if os.path.exists(path_or_id) and os.path.isfile(path_or_id):
        audio_path = path_or_id
        print(f"使用指定的音频文件: {audio_path}")
        
        # 腾讯云ASR转写
        print("\n[腾讯云ASR] 开始转写...")
        text = tencent_asr.recognize(audio_path)
        if text:
            print("\n[腾讯云ASR] 识别结果:")
            print("=" * 40)
            print(text)
            print("=" * 40)
        else:
            print("[腾讯云ASR] 识别失败")
        
        # Whisper转写
        print("\n[Whisper] 开始转写...")
        text2 = client.transcribe_audio(audio_path)
        if text2:
            print("\n[Whisper] 识别结果:")
            print("=" * 40)
            print(text2)
            print("=" * 40)
        else:
            print("[Whisper] 识别失败")
        return
    
    # 使用douyin_id从数据库查找
    else:
        douyin_id = path_or_id
        print(f"使用抖音ID: {douyin_id}")
        
        db = Database()
        video = db.get_douyin_video_by_id(douyin_id)
        
        if not video:
            print(f"未找到抖音ID为 {douyin_id} 的视频")
            return
        
        audio_path = video[11]  # audio_path列
        
        if not audio_path or not os.path.exists(audio_path):
            print(f"未找到音频文件或文件不存在: {audio_path}")
            return
        
        print(f"找到音频文件: {audio_path}")
        
        # 如果已有音频转写文本，先显示
        if video[13]:  # audio_text列
            print("\n数据库中已有音频转写结果:")
            print("=" * 40)
            print(video[13])
            print("=" * 40)
            
            # 询问是否重新转写
            response = input("\n是否重新转写? (y/n): ")
            if response.lower() != 'y':
                return
        
        # 转写音频
        text = client.transcribe_audio(audio_path)
        if text:
            print("\n新的音频转写结果:")
            print("=" * 40)
            print(text)
            print("=" * 40)
            
            # 保存到文本文件
            txt_path = os.path.splitext(audio_path)[0] + ".txt"
            if client.save_text_to_file(text, txt_path):
                print(f"\n结果已保存至: {txt_path}")
            
            # 更新数据库
            db.update_douyin_video_status(douyin_id, status=video[14], audio_text=text)
            print("数据库记录已更新")
        else:
            print("音频转写失败")

if __name__ == "__main__":
    main() 