import json
import logging
from pathlib import Path
from .deepseek_client import DeepSeekClient
from database.database import Database

# 设置日志记录器
ai_logger = logging.getLogger('ai')

class DouyinTextProcessor:
    def __init__(self):
        """初始化抖音文本处理器"""
        self.deepseek = DeepSeekClient()
        self.db = Database()
        ai_logger.info("抖音文本处理器初始化完成")
    
    def process_audio_text(self, douyin_id, audio_text, video_id=None):
        """处理音频转写文本
        
        Args:
            douyin_id: 抖音视频ID
            audio_text: 原始音频转写文本
            video_id: 视频数据库ID（如果已知）
            
        Returns:
            处理结果字典 {
                "polished_text": "润色后的文本",
                "novels": [
                    {
                        "novel_name": "识别出的小说名1",
                        "novel_id": 123,  # 数据库中的小说ID，如未找到则为None
                        "summary": "关于该小说的描述",
                        "confidence": 0.85  # 识别置信度
                    },
                    {
                        "novel_name": "识别出的小说名2",
                        "novel_id": null,  
                        "summary": "关于该小说的描述",
                        "confidence": 0.7
                    }
                ]
            }
        """
        if not audio_text or len(audio_text.strip()) < 10:
            ai_logger.warning(f"音频文本内容过短或为空，无法处理: {douyin_id}")
            return None
        
        # 获取所有小说名称列表
        novels = self.db.get_all_novel_names(limit=200)
        novel_info = "\n".join([f"ID: {n[0]}, 标题: {n[1]}, 作者: {n[2]}" for n in novels])
        
        # 构建提示词
        prompt = f"""你是一个专业的中文AI写作助手。以下是抖音视频的口播文字稿，请你：

1. 给这段文字加上合适的标点符号，修正错别字，优化为接近视频原貌的演讲稿风格。
2. 判断这段文字是否与下方小说库中的某些小说相关联，识别出所有提到的小说。
3. 对于每部识别到的小说，提取视频中关于该小说的描述内容作为summary。

【抖音视频口播文字稿】：
{audio_text}

【小说库】：
{novel_info}

请以如下JSON格式返回：
{{
  "polished_text": "润色后的文字稿",
  "novels": [
    {{
      "novel_name": "识别出的小说名称1",
      "novel_id": 123,  // 从小说库中匹配的ID，如未找到则为null
      "summary": "视频中关于该小说的描述", 
      "confidence": 0.9  // 识别置信度，0-1之间的浮点数
    }},
    {{
      "novel_name": "识别出的小说名称2",
      "novel_id": null,  // 未在小说库中找到匹配ID
      "summary": "视频中关于该小说的描述",
      "confidence": 0.7
    }}
    // 可能有更多小说...
  ]
}}

如果没有识别到任何小说，则返回空数组：
{{
  "polished_text": "润色后的文字稿",
  "novels": []
}}
"""
        
        # 调用DeepSeek进行处理
        ai_logger.info(f"开始处理抖音视频音频文本: {douyin_id}")
        response = self.deepseek._call_api(prompt)
        
        if not response:
            ai_logger.error(f"处理音频文本失败: {douyin_id}")
            return None
        
        # 解析响应
        result = self.deepseek._parse_json_response(response)
        if not result:
            # 如果JSON解析失败，尝试直接提取
            ai_logger.warning(f"JSON解析失败，尝试直接提取: {douyin_id}")
            result = {
                "polished_text": response,
                "novels": []
            }
        
        # 日志记录处理结果
        novels_count = len(result.get("novels", []))
        ai_logger.info(f"音频文本处理成功: {douyin_id}, 识别到 {novels_count} 部小说")
        
        # 如果没有提供数据库ID，则查询
        if not video_id:
            video = self.db.get_douyin_video_by_id(douyin_id)
            if video:
                video_id = video[0]  # 数据库ID
        
        # 保存到数据库
        if video_id:
            # 更新抖音视频表中的音频文本
            self.db.update_douyin_video_status(
                douyin_id, 
                status="completed", 
                audio_text=result.get("polished_text", audio_text)
            )
            
            # 保存关联信息到douyin_video_novel表（可能有多部小说）
            for novel_info in result.get("novels", []):
                novel_name = novel_info.get("novel_name", "未知")
                novel_id = novel_info.get("novel_id")
                confidence = novel_info.get("confidence", 0)
                summary = novel_info.get("summary", "")
                
                # 记录日志
                if novel_id:
                    ai_logger.info(f"识别到小说 '{novel_name}' (ID: {novel_id}), 置信度: {confidence}")
                else:
                    ai_logger.info(f"识别到未收录小说 '{novel_name}', 置信度: {confidence}")
                
                # 插入关联记录
                self.db.insert_douyin_video_novel(
                    douyin_video_id=video_id,
                    novel_id=novel_id,
                    novel_name=novel_name,
                    confidence=confidence,
                    summary=summary
                )
        
        return result
    
    def save_processed_text(self, douyin_id, text, file_path=None):
        """将处理后的文本保存到音频目录下，文件名为{douyin_id}_processed.txt，已存在则覆盖
        
        Args:
            douyin_id: 抖音视频ID
            text: 处理后的文本
            file_path: 指定的文件路径，如果不提供则自动查找audio目录
            
        Returns:
            保存的文件路径
        """
        if not file_path:
            # 查询视频记录获取音频目录
            video = self.db.get_douyin_video_by_id(douyin_id)
            if not video or not video[12]:  # audio_dir
                ai_logger.warning(f"未找到视频记录或音频目录: {douyin_id}")
                return None
            audio_dir = video[12]
            file_path = Path(audio_dir) / f"{douyin_id}_processed.txt"
        try:
            # 确保目录存在
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            # 写入文件（覆盖）
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(text)
            ai_logger.info(f"处理后的文本已保存: {file_path}")
            return str(file_path)
        except Exception as e:
            ai_logger.error(f"保存处理后的文本失败: {file_path}, 错误: {str(e)}")
            return None 