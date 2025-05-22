import os
import json
import logging
import requests
import time
import re
import whisper
from pathlib import Path
from apify_client import ApifyClient
from database.database import Database
from config.config import APIFY_CONFIG
from ai_client.tencent_asr import TencentASRClient
from ai_client.douyin_text_processor import DouyinTextProcessor

# 设置日志记录器
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/douyin_spider.log')
    ]
)
logger = logging.getLogger('douyin_spider')

class DouyinSpiderClient:
    def __init__(self):
        """初始化抖音爬虫客户端"""
        self.db = Database()
        self.api_token = APIFY_CONFIG.get('api_token')
        if not self.api_token:
            raise ValueError("缺少APIFY_TOKEN，请在.env文件中配置")
        
        self.client = ApifyClient(self.api_token)
        logger.info("抖音爬虫客户端初始化完成")
        
        # 创建必要的文件夹
        self.base_dir = Path("data/douyin")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化Whisper模型，默认使用base模型，速度较快且精度适中
        # 可选模型大小: tiny, base, small, medium, large
        self.whisper_model = None  # 延迟加载
        self.tencent_asr = TencentASRClient()
        self.text_processor = DouyinTextProcessor()  # 添加文本处理器
    
    def load_whisper_model(self, model_size="base"):
        """加载Whisper语音识别模型
        
        Args:
            model_size: 模型大小，可选 tiny, base, small, medium, large
        """
        if self.whisper_model is None:
            logger.info(f"加载Whisper模型: {model_size}")
            try:
                self.whisper_model = whisper.load_model(model_size)
                logger.info("Whisper模型加载成功")
            except Exception as e:
                logger.error(f"加载Whisper模型失败: {str(e)}")
                return False
        return True
    
    def transcribe_audio(self, audio_path):
        """优先用腾讯云ASR转写，失败再用whisper兜底"""
        try:
            # 获取视频时长（如果有）
            duration_ms = None
            try:
                # 从文件路径提取douyin_id
                douyin_id = os.path.basename(audio_path).split('.')[0]
                # 查询数据库获取视频时长
                video = self.db.get_douyin_video_by_id(douyin_id)
                if video and video[6]:  # duration字段
                    duration_ms = video[6]
                    logger.info(f"获取到视频时长: {duration_ms} 毫秒")
            except Exception as e:
                logger.warning(f"获取视频时长失败: {str(e)}")
            
            # 先用腾讯云ASR（使用自动选择功能）
            text = self.tencent_asr.recognize_auto(audio_path, duration_ms=duration_ms)
            if text:
                logger.info(f"[腾讯云ASR] 音频转写成功: {audio_path}, 长度: {len(text)} 字符")
                return text
            else:
                logger.warning(f"[腾讯云ASR] 识别失败，尝试Whisper兜底: {audio_path}")
        except Exception as e:
            logger.error(f"[腾讯云ASR] 转写失败: {audio_path}, 错误: {str(e)}")
        # Whisper兜底
        try:
            if not self.load_whisper_model():
                return None
            logger.info(f"[Whisper] 开始转写: {audio_path}")
            result = self.whisper_model.transcribe(audio_path)
            text = result.get("text", "").strip()
            if text:
                logger.info(f"[Whisper] 音频转写成功: {audio_path}, 长度: {len(text)} 字符")
                return text
            else:
                logger.warning(f"[Whisper] 识别结果为空: {audio_path}")
                return None
        except Exception as e:
            logger.error(f"[Whisper] 转写失败: {audio_path}, 错误: {str(e)}")
            return None
    
    def save_text_to_file(self, text, txt_path):
        """将文本保存到文件
        
        Args:
            text: 要保存的文本
            txt_path: 文本文件路径
            
        Returns:
            是否保存成功
        """
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(txt_path), exist_ok=True)
            
            # 写入文件
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(text)
                
            logger.info(f"文本保存成功: {txt_path}")
            return True
            
        except Exception as e:
            logger.error(f"保存文本失败: {txt_path}, 错误: {str(e)}")
            return False
    
    def fetch_video_info(self, video_url):
        """从Apify获取抖音视频信息
        
        Args:
            video_url: 抖音视频URL
            
        Returns:
            视频信息，如果失败则返回None
        """
        logger.info(f"开始获取视频信息: {video_url}")
        
        try:
            # 准备Actor输入
            run_input = {
                "links": [video_url],
                "proxyConfiguration": {
                    "useApifyProxy": True,
                    "apifyProxyGroups": ["RESIDENTIAL"],
                },
            }
            
            # 运行Actor并等待完成
            run = self.client.actor("zWEMpLvAjS6EM1gGZ").call(run_input=run_input)
            
            # 获取结果
            results = []
            for item in self.client.dataset(run["defaultDatasetId"]).iterate_items():
                results.append(item)
            
            if not results:
                logger.warning(f"没有获取到视频信息: {video_url}")
                return None
            
            # 返回第一个结果的result部分，如果有
            if "result" in results[0]:
                data = results[0]["result"]
                logger.info(f"成功获取视频信息: {video_url}, ID: {data.get('id', 'unknown')}")
                return data
            else:
                logger.info(f"成功获取视频信息: {video_url}")
                return results[0]  # 返回第一个结果
            
        except Exception as e:
            logger.error(f"获取视频信息失败: {video_url}, 错误: {str(e)}")
            return None
    
    def save_video_to_database(self, video_info):
        """将视频信息保存到数据库
        
        Args:
            video_info: 视频信息字典
            
        Returns:
            视频ID，如果失败则返回None
        """
        try:
            if not video_info:
                return None
                
            # 检查视频信息是否完整
            if "id" not in video_info:
                logger.warning("视频信息不完整，缺少必要字段 'id'")
                return None
                
            # 提取必要字段
            douyin_id = video_info.get("id")
            unique_id = video_info.get("unique_id")
            author = video_info.get("author")
            title = video_info.get("title")
            thumbnail_url = video_info.get("thumbnail")
            duration = video_info.get("duration")
            source_url = video_info.get("url")
            
            # 保存到数据库
            video_id = self.db.insert_douyin_video(
                douyin_id=douyin_id,
                unique_id=unique_id,
                author=author,
                title=title,
                thumbnail_url=thumbnail_url,
                duration=duration,
                source_url=source_url,
                content=video_info
            )
            
            logger.info(f"保存视频信息到数据库: ID {video_id} - 标题: {title[:30] if title else 'Unknown'}")
            return video_id
            
        except Exception as e:
            logger.error(f"保存视频信息到数据库失败: {str(e)}")
            return None
    
    def sanitize_filename(self, filename):
        """清理文件名，去除不合法字符
        
        Args:
            filename: 原始文件名
            
        Returns:
            清理后的文件名
        """
        # 替换不合法的文件名字符
        sanitized = re.sub(r'[\\/*?:"<>|]', "_", filename)
        # 移除表情符号和特殊字符
        sanitized = re.sub(r'[^\w\-_\. ]', '', sanitized)
        # 如果文件名为空，使用默认名称
        if not sanitized.strip():
            return "douyin_video"
        return sanitized
    
    def download_file(self, url, file_path):
        """下载文件
        
        Args:
            url: 文件URL
            file_path: 保存路径
            
        Returns:
            是否下载成功
        """
        try:
            # 创建目录
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            # 下载文件
            response = requests.get(url, stream=True)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            logger.info(f"开始下载文件: {url} -> {file_path}, 大小: {total_size/1024/1024:.2f}MB")
            
            # 写入文件
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    
            logger.info(f"文件下载成功: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"文件下载失败: {url} -> {file_path}, 错误: {str(e)}")
            return False
    
    def download_video(self, douyin_id):
        """下载视频和音频文件
        
        Args:
            douyin_id: 抖音视频ID
            
        Returns:
            是否下载成功
        """
        try:
            # 先更新状态为downloading
            self.db.update_douyin_video_status(douyin_id, 'downloading')
            
            # 获取视频信息
            video_record = self.db.get_douyin_video_by_id(douyin_id)
            if not video_record:
                logger.warning(f"未找到视频记录: {douyin_id}")
                return False
                
            # 解析JSON内容
            content = json.loads(video_record[16]) if video_record[16] else {}
            
            if not content or "medias" not in content:
                error_msg = "视频信息不完整，无法下载"
                self.db.update_douyin_video_status(douyin_id, 'failed', error_message=error_msg)
                logger.warning(f"{error_msg}: {douyin_id}")
                return False
            
            # 获取视频标题并清理
            title = self.sanitize_filename(video_record[4] or f"video_{douyin_id}")
            
            # 创建视频目录
            video_dir = os.path.join(self.base_dir, title)
            os.makedirs(video_dir, exist_ok=True)
            
            # 视频和音频子目录
            video_subdir = os.path.join(video_dir, "video")
            audio_subdir = os.path.join(video_dir, "audio")
            
            os.makedirs(video_subdir, exist_ok=True)
            os.makedirs(audio_subdir, exist_ok=True)
            
            # 查找最佳视频和音频URL
            video_url = None
            audio_url = None
            
            # 首先寻找HD No Watermark格式的视频
            for media in content.get("medias", []):
                media_type = media.get("type")
                quality = media.get("quality", "")
                
                if media_type == "video" and "HD No Watermark" in quality and not video_url:
                    video_url = media.get("url")
                elif media_type == "audio" and not audio_url:
                    audio_url = media.get("url")
            
            # 如果没有找到HD No Watermark，寻找普通No Watermark
            if not video_url:
                for media in content.get("medias", []):
                    media_type = media.get("type")
                    quality = media.get("quality", "")
                    
                    if media_type == "video" and "No Watermark" in quality and not video_url:
                        video_url = media.get("url")
            
            # 如果仍然没有找到无水印视频，使用第一个视频链接
            if not video_url and content.get("medias"):
                for media in content.get("medias", []):
                    if media.get("type") == "video":
                        video_url = media.get("url")
                        break
            
            # 下载和保存文件
            video_path = None
            audio_path = None
            audio_text = None
            processed_text = None
            audio_text_path = None
            
            # 下载视频
            if video_url:
                video_filename = f"{douyin_id}.mp4"
                video_path = os.path.join(video_subdir, video_filename)
                if self.download_file(video_url, video_path):
                    logger.info(f"视频下载成功: {video_path}")
                else:
                    video_path = None
            
            # 下载音频并转写文本
            if audio_url:
                audio_filename = f"{douyin_id}.mp3"
                audio_path = os.path.join(audio_subdir, audio_filename)
                
                if self.download_file(audio_url, audio_path):
                    logger.info(f"音频下载成功: {audio_path}")
                    
                    # 尝试转写音频
                    audio_text = self.transcribe_audio(audio_path)
                    if audio_text:
                        # 保存原始转写文本到文件
                        audio_text_path = os.path.join(audio_subdir, f"{douyin_id}.txt")
                        self.save_text_to_file(audio_text, audio_text_path)
                        logger.info(f"原始音频转写成功并保存: {audio_text_path}")
                        
                        # 使用文本处理器进行润色和小说识别
                        logger.info(f"开始处理音频文本: {douyin_id}")
                        video_id = video_record[0]  # 数据库ID
                        result = self.text_processor.process_audio_text(douyin_id, audio_text, video_id)
                        
                        if result:
                            # 获取润色后的文本
                            processed_text = result.get("polished_text")
                            
                            # 保存润色后的文本到文件
                            processed_text_path = os.path.join(audio_subdir, f"{douyin_id}_processed.txt")
                            self.save_text_to_file(processed_text, processed_text_path)
                            logger.info(f"处理后的文本已保存: {processed_text_path}")
                            
                            # 输出识别到的小说信息
                            novel_name = result.get("novel_name", "未知")
                            novel_id = result.get("novel_id")
                            confidence = result.get("confidence", 0)
                            
                            if novel_name and novel_name != "未知":
                                logger.info(f"识别到相关小说: {novel_name} (ID: {novel_id}, 置信度: {confidence:.2f})")
                            else:
                                logger.info("未识别到相关小说")
                                
                            # 使用处理后的文本作为最终音频文本
                            audio_text = processed_text
                    else:
                        logger.warning(f"音频转写失败: {audio_path}")
                else:
                    audio_path = None
            
            # 更新数据库状态
            if video_path or audio_path:
                self.db.update_douyin_video_status(
                    douyin_id, 
                    'completed', 
                    video_path=video_path,
                    audio_path=audio_path,
                    video_dir=video_subdir,
                    audio_dir=audio_subdir,
                    audio_text=audio_text
                )
                logger.info(f"完成视频下载: {douyin_id} - {title}")
                return True
            else:
                error_msg = "无法下载视频或音频"
                self.db.update_douyin_video_status(douyin_id, 'failed', error_message=error_msg)
                logger.warning(f"{error_msg}: {douyin_id}")
                return False
                
        except Exception as e:
            error_msg = f"下载视频失败: {str(e)}"
            self.db.update_douyin_video_status(douyin_id, 'failed', error_message=error_msg)
            logger.error(f"下载视频失败: {douyin_id}, 错误: {str(e)}")
            return False
    
    def process_pending_videos(self, limit=5):
        """处理等待下载的视频
        
        Args:
            limit: 最多处理的视频数
            
        Returns:
            处理的视频数
        """
        # 获取等待下载的视频
        pending_videos = self.db.get_pending_douyin_videos(limit=limit)
        
        count = 0
        for video in pending_videos:
            douyin_id = video[1]  # douyin_id字段
            logger.info(f"开始处理视频: {douyin_id}")
            
            success = self.download_video(douyin_id)
            if success:
                count += 1
            
            # 避免过快请求
            time.sleep(1)
        
        logger.info(f"完成处理 {count}/{len(pending_videos)} 个待下载视频")
        return count
    
    def process_url(self, url):
        """处理单个URL
        
        Args:
            url: 抖音视频URL
            
        Returns:
            是否成功处理
        """
        try:
            # 获取视频信息
            video_info = self.fetch_video_info(url)
            if not video_info:
                logger.error(f"无法获取视频信息: {url}")
                return False
                
            # 保存到数据库
            video_id = self.save_video_to_database(video_info)
            if not video_id:
                logger.error(f"保存视频信息失败: {url}")
                return False
                
            # 下载视频
            douyin_id = video_info.get("id")
            result = self.download_video(douyin_id)
            
            if result:
                logger.info(f"成功处理视频: {url}")
            else:
                logger.error(f"下载视频失败: {url}")
                
            return result
            
        except Exception as e:
            logger.error(f"处理URL失败: {url}, 错误: {str(e)}")
            return False

def main():
    """主函数"""
    try:
        # 创建日志目录
        os.makedirs("logs", exist_ok=True)
        
        # 检查命令行参数
        import sys
        
        # 初始化爬虫客户端
        client = DouyinSpiderClient()
        
        if len(sys.argv) > 1:
            # 命令行参数处理
            if sys.argv[1] == "--process-pending":
                # 处理待下载队列
                limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
                count = client.process_pending_videos(limit=limit)
                logger.info(f"批量处理完成，共处理 {count} 个视频")
            else:
                # 将第一个参数作为URL处理
                url = sys.argv[1]
                logger.info(f"从命令行获取URL: {url}")
                client.process_url(url)
        else:
            # 无参数，默认处理待下载队列
            count = client.process_pending_videos(limit=10)
            logger.info(f"批量处理完成，共处理 {count} 个视频")
        
    except Exception as e:
        logger.error(f"程序运行出错: {str(e)}")

if __name__ == "__main__":
    main() 