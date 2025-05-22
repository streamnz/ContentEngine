#!/bin/bash

# 帮助信息
function show_help() {
  echo "抖音视频下载工具"
  echo ""
  echo "用法:"
  echo "  ./download_douyin.sh <抖音视频URL>      - 下载单个视频"
  echo "  ./download_douyin.sh -p [数量]         - 处理指定数量的待下载视频"
  echo "  ./download_douyin.sh -a <URL>          - 仅添加URL到下载队列" 
  echo "  ./download_douyin.sh -t <ID>           - 将音频转为文本"
  echo "  ./download_douyin.sh -pt <ID>          - 润色文本并识别小说"
  echo ""
  echo "示例:"
  echo "  ./download_douyin.sh https://www.douyin.com/video/7045159024525905183"
  echo "  ./download_douyin.sh -p 5"
  echo "  ./download_douyin.sh -pt 7496842121786314035"
}

# 参数映射
case "$1" in
  -h|--help)
    show_help
    ;;
  -p|--pending)
    PYTHONPATH=. python douyin_spider/download_douyin.py --process-pending "${2:-10}"
    ;;
  -a|--add)
    PYTHONPATH=. python douyin_spider/download_douyin.py --add-url "$2"
    ;;
  -t|--trans)
    PYTHONPATH=. python douyin_spider/download_douyin.py --transcribe "$2"
    ;;
  -pt|--text)
    PYTHONPATH=. python douyin_spider/download_douyin.py --process-text "$2"
    ;;
  "")
    show_help
    ;;
  *)
    PYTHONPATH=. python douyin_spider/download_douyin.py "$@"
    ;;
esac 