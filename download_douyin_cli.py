#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
抖音视频下载工具 (命令行入口)

用法:
    python download_douyin_cli.py [抖音视频URL]     - 下载单个视频
    python download_douyin_cli.py --pending [数量]   - 处理指定数量的待下载视频
    python download_douyin_cli.py --add [URL]        - 仅添加URL到下载队列
    python download_douyin_cli.py --trans [ID]       - 将音频转为文本
    python download_douyin_cli.py --text [ID]        - 润色文本并识别小说

示例:
    python download_douyin_cli.py https://www.douyin.com/video/7045159024525905183
    python download_douyin_cli.py --pending 5
    python download_douyin_cli.py --text 7496842121786314035
"""

import sys
import os

# 简单别名映射
ALIAS_MAP = {
    "--help": "--help",
    "-h": "--help",
    "--pending": "--process-pending",
    "-p": "--process-pending",
    "--add": "--add-url",
    "-a": "--add-url",
    "--trans": "--transcribe",
    "-t": "--transcribe",
    "--text": "--process-text",
    "-pt": "--process-text"
}

def main():
    # 重映射参数
    args = sys.argv[1:]
    
    # 没有参数时显示帮助
    if not args:
        # 执行帮助命令
        os.system(f"python douyin_spider/download_douyin.py --help")
        return
    
    # 转换别名
    if args[0] in ALIAS_MAP:
        args[0] = ALIAS_MAP[args[0]]
    
    # 拼接命令和参数
    cmd_args = " ".join(args)
    
    # 执行命令
    os.system(f"python douyin_spider/download_douyin.py {cmd_args}")

if __name__ == "__main__":
    main() 