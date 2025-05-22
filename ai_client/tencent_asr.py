import os
import time
from config.config import TENCENTCLOUD_CONFIG
from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.asr.v20190614 import asr_client, models
import json
import logging

# 设置日志记录器
asr_logger = logging.getLogger('asr')

class TencentASRClient:
    def __init__(self):
        self.appid = TENCENTCLOUD_CONFIG['appid']
        self.secret_id = TENCENTCLOUD_CONFIG['secret_id']
        self.secret_key = TENCENTCLOUD_CONFIG['secret_key']
        self.endpoint = "asr.tencentcloudapi.com"

    def recognize(self, audio_path, engine_model_type="16k_zh", res_text_format=0):
        """短音频识别（一句话识别，适用于60秒以内的音频）
        
        Args:
            audio_path: 音频文件路径
            engine_model_type: 引擎模型类型
            res_text_format: 结果文本格式
            
        Returns:
            识别结果文本
        """
        cred = credential.Credential(self.secret_id, self.secret_key)
        httpProfile = HttpProfile()
        httpProfile.endpoint = self.endpoint
        clientProfile = ClientProfile()
        clientProfile.httpProfile = httpProfile
        client = asr_client.AsrClient(cred, "ap-guangzhou", clientProfile)

        with open(audio_path, "rb") as f:
            audio_data = f.read()
        import base64
        audio_base64 = base64.b64encode(audio_data).decode("utf-8")

        req = models.SentenceRecognitionRequest()
        params = {
            "ProjectId": 0,
            "SubServiceType": 2,
            "EngSerViceType": engine_model_type,
            "SourceType": 1,
            "VoiceFormat": "mp3",
            "UsrAudioKey": os.path.basename(audio_path),
            "Data": audio_base64,
            "ResTextFormat": res_text_format
        }
        req.from_json_string(json.dumps(params))
        resp = client.SentenceRecognition(req)
        return resp.Result
        
    def recognize_long_audio(self, audio_path, engine_model_type="16k_zh", 
                           channel_num=1, res_text_format=0, filter_modal=0,
                           filter_punc=0, convert_nums=1, word_info=0,
                           max_retry=10, retry_interval=5):
        """长音频识别（录音文件识别，适用于60秒以上的长音频文件）
        
        Args:
            audio_path: 音频文件路径
            engine_model_type: 引擎模型类型
            channel_num: 音频声道数，1或2
            res_text_format: 结果文本格式
            filter_modal: 是否过滤语气词
            filter_punc: 是否过滤标点符号
            convert_nums: 是否转换数字为阿拉伯数字
            word_info: 是否显示词级别时间戳
            max_retry: 最大重试次数
            retry_interval: 重试间隔（秒）
            
        Returns:
            识别结果文本
        """
        try:
            asr_logger.info(f"开始长音频识别: {audio_path}")
            
            # 初始化客户端
            cred = credential.Credential(self.secret_id, self.secret_key)
            httpProfile = HttpProfile()
            httpProfile.endpoint = self.endpoint
            clientProfile = ClientProfile()
            clientProfile.httpProfile = httpProfile
            client = asr_client.AsrClient(cred, "ap-guangzhou", clientProfile)
            
            # 准备音频URL（如果是本地文件，可以考虑上传到COS或其他存储）
            # 这里假设音频文件已经可以通过URL访问，或者是本地文件
            audio_url = None
            if audio_path.startswith(('http://', 'https://')):
                audio_url = audio_path
                source_type = 0  # URL访问
            else:
                # 如果是本地文件，需要读取文件内容并base64编码
                with open(audio_path, "rb") as f:
                    audio_data = f.read()
                import base64
                audio_base64 = base64.b64encode(audio_data).decode("utf-8")
                source_type = 1  # 语音数据

            # 创建录音文件识别请求
            req = models.CreateRecTaskRequest()
            params = {
                "EngineModelType": engine_model_type,
                "ChannelNum": channel_num,
                "ResTextFormat": res_text_format,
                "FilterModal": filter_modal,
                "FilterPunc": filter_punc,
                "ConvertNumMode": convert_nums,
                "WordInfo": word_info
            }
            
            # 根据音频来源设置参数
            if source_type == 0:
                params["SourceType"] = 0
                params["Url"] = audio_url
            else:
                params["SourceType"] = 1
                params["Data"] = audio_base64
                
            req.from_json_string(json.dumps(params))
            
            # 发送创建识别任务请求
            create_resp = client.CreateRecTask(req)
            task_id = create_resp.Data.TaskId
            asr_logger.info(f"创建长音频识别任务成功: TaskId={task_id}")
            
            # 轮询任务结果
            retry_count = 0
            while retry_count < max_retry:
                time.sleep(retry_interval)
                
                # 创建查询任务请求
                describe_req = models.DescribeTaskStatusRequest()
                describe_req.from_json_string(json.dumps({"TaskId": task_id}))
                
                # 查询任务状态
                describe_resp = client.DescribeTaskStatus(describe_req)
                task_status = describe_resp.Data.Status
                
                asr_logger.info(f"任务状态: TaskId={task_id}, Status={task_status}")
                
                # 任务完成
                if task_status == 2:  # 2表示任务完成
                    result = describe_resp.Data.Result
                    asr_logger.info(f"长音频识别完成: TaskId={task_id}")
                    return result
                    
                # 任务失败
                elif task_status == 3:  # 3表示任务失败
                    error_msg = describe_resp.Data.ErrorMsg
                    asr_logger.error(f"长音频识别失败: TaskId={task_id}, 错误: {error_msg}")
                    return None
                    
                # 任务进行中，继续轮询
                retry_count += 1
                
            # 超过最大重试次数
            asr_logger.warning(f"长音频识别超时: TaskId={task_id}, 已重试{max_retry}次")
            return None
            
        except Exception as e:
            asr_logger.error(f"长音频识别异常: {str(e)}")
            return None
            
    def recognize_auto(self, audio_path, engine_model_type="16k_zh", duration_ms=None):
        """智能识别音频，根据音频长度自动选择短音频或长音频识别
        
        Args:
            audio_path: 音频文件路径
            engine_model_type: 引擎模型类型 
            duration_ms: 音频时长(毫秒)，如果不提供则自动检测
            
        Returns:
            识别结果文本
        """
        # 判断音频长度，如果超过60秒则使用长音频识别
        threshold_ms = 60000  # 60秒阈值
        
        if duration_ms is None:
            # 可以考虑使用ffprobe等工具获取音频时长
            # 这里简单实现，默认长音频识别
            asr_logger.info(f"未提供音频时长，默认使用长音频识别: {audio_path}")
            return self.recognize_long_audio(audio_path, engine_model_type=engine_model_type)
            
        if duration_ms > threshold_ms:
            asr_logger.info(f"音频时长 {duration_ms/1000:.2f} 秒，使用长音频识别")
            return self.recognize_long_audio(audio_path, engine_model_type=engine_model_type)
        else:
            asr_logger.info(f"音频时长 {duration_ms/1000:.2f} 秒，使用短音频识别")
            return self.recognize(audio_path, engine_model_type=engine_model_type) 