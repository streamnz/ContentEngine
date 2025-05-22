import mysql.connector
import json
import logging
from config import DB_CONFIG

# 获取数据库专用logger
db_logger = logging.getLogger('database')

class Database:
    def __init__(self):
        self.connection = mysql.connector.connect(**DB_CONFIG)
        self.cursor = self.connection.cursor()
        self.init_tables()  # 初始化表结构
        db_logger.info("数据库连接初始化完成")

    def init_tables(self):
        """初始化数据库表结构，如果表不存在则创建"""
        # 创建小说分类表
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS novel_category (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            name VARCHAR(255) NOT NULL,
            en_name VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # 创建小说表
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS novel (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            title VARCHAR(255) NOT NULL,
            author VARCHAR(255),
            description TEXT,
            source_url VARCHAR(500),
            category_id BIGINT,
            chapter_count INT DEFAULT 0,
            status VARCHAR(50) DEFAULT 'incomplete',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY (title),
            FOREIGN KEY (category_id) REFERENCES novel_category(id) ON DELETE SET NULL
        )
        """)
        
        # 创建章节表
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS novel_chapter (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            novel_id BIGINT NOT NULL,
            chapter_index INT NOT NULL,
            chapter_title VARCHAR(255),
            chapter_url VARCHAR(500),
            summary_100 TEXT,
            summary LONGTEXT,
            outline_structured JSON,
            storyboard_structured JSON,
            content_cn LONGTEXT,
            content_en LONGTEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY (novel_id, chapter_index),
            FOREIGN KEY (novel_id) REFERENCES novel(id) ON DELETE CASCADE
        )
        """)
        
        # 创建抖音视频表
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS douyin_video (
            id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
            douyin_id VARCHAR(64) COMMENT '抖音视频ID',
            unique_id VARCHAR(64) COMMENT '抖音作者唯一ID',
            author VARCHAR(255) COMMENT '作者昵称',
            title VARCHAR(512) COMMENT '视频标题',
            thumbnail_url VARCHAR(1024) COMMENT '封面图URL',
            duration INT COMMENT '视频时长（毫秒）',
            source_url VARCHAR(1024) NOT NULL COMMENT '原始抖音URL',
            source_url_hash CHAR(32) GENERATED ALWAYS AS (MD5(source_url)) STORED COMMENT '原始URL的MD5哈希',
            video_dir VARCHAR(1024) COMMENT '本地视频文件目录',
            video_path VARCHAR(1024) COMMENT '本地视频文件路径',
            audio_dir VARCHAR(1024) COMMENT '本地音频文件目录',
            audio_path VARCHAR(1024) COMMENT '本地音频文件路径',
            audio_text LONGTEXT COMMENT '音频转文字内容',
            status VARCHAR(32) DEFAULT 'pending' COMMENT '下载状态(pending/downloading/completed/failed)',
            error_message VARCHAR(1024) COMMENT '失败原因',
            content JSON COMMENT '完整响应内容',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
            UNIQUE KEY (source_url_hash)
        )
        """)
        
        # 创建抖音视频与小说关联表（多对多关系）
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS douyin_video_novel (
            id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
            douyin_video_id BIGINT NOT NULL COMMENT '抖音视频ID',
            novel_id BIGINT COMMENT '小说ID',
            novel_name VARCHAR(255) NOT NULL COMMENT '小说名称',
            confidence FLOAT DEFAULT 0 COMMENT 'AI识别置信度',
            summary TEXT COMMENT '关于该小说的内容描述',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
            FOREIGN KEY (douyin_video_id) REFERENCES douyin_video(id) ON DELETE CASCADE,
            FOREIGN KEY (novel_id) REFERENCES novel(id) ON DELETE SET NULL,
            UNIQUE KEY (douyin_video_id, novel_name)
        ) COMMENT='抖音视频与小说关联表'
        """)
        
        # 创建待收录小说表
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS to_do_novel (
            id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
            novel_name VARCHAR(255) NOT NULL COMMENT '小说名称',
            douyin_video_id BIGINT COMMENT '关联的抖音视频ID',
            recommendation_reason TEXT COMMENT '推荐原因（视频中的描述）',
            status VARCHAR(32) DEFAULT 'pending' COMMENT '状态(pending/ignored/added)',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
            UNIQUE KEY (novel_name),
            FOREIGN KEY (douyin_video_id) REFERENCES douyin_video(id) ON DELETE SET NULL
        ) COMMENT='待收录小说表'
        """)
        
        # 检查novel_category表是否为空，如果为空则插入默认分类
        self.cursor.execute("SELECT COUNT(*) FROM novel_category")
        count = self.cursor.fetchone()[0]
        if count == 0:
            # 插入默认分类
            default_categories = [
                ("玄幻", "Fantasy"),
                ("武侠", "Martial Arts"),
                ("都市", "Urban"),
                ("历史", "Historical"),
                ("科幻", "Science Fiction"),
                ("游戏", "Gaming"),
                ("其他", "Others")
            ]
            
            for name, en_name in default_categories:
                self.cursor.execute(
                    "INSERT INTO novel_category (name, en_name) VALUES (%s, %s)",
                    (name, en_name)
                )
            db_logger.info("初始化默认分类完成")
        
        self.connection.commit()
        db_logger.info("数据库表结构检查完成")

    def close(self):
        self.cursor.close()
        self.connection.close()
        db_logger.info("数据库连接已关闭")

    # === 抖音视频相关方法 ===
    
    def insert_douyin_video(self, source_url, douyin_id=None, unique_id=None, author=None, title=None, 
                          thumbnail_url=None, duration=None, content=None):
        """插入抖音视频记录
        
        Args:
            source_url: 抖音视频URL (必填)
            douyin_id: 抖音视频ID
            unique_id: 抖音作者唯一ID
            author: 作者昵称
            title: 视频标题
            thumbnail_url: 封面图片URL
            duration: 视频时长(毫秒)
            content: 完整响应内容(JSON)
            
        Returns:
            记录ID，如果插入失败则返回None
        """
        try:
            # 检查是否已存在相同URL的记录
            sql = "SELECT id FROM douyin_video WHERE source_url = %s"
            self.cursor.execute(sql, (source_url,))
            existing_record = self.cursor.fetchone()
            
            if existing_record:
                db_logger.info(f"已存在相同URL的视频记录: {source_url}, ID: {existing_record[0]}")
                return existing_record[0]
            
            # 处理JSON内容
            content_json = json.dumps(content, ensure_ascii=False) if content else None
            
            # 准备插入数据
            sql = """
            INSERT INTO douyin_video (
                douyin_id, unique_id, author, title, thumbnail_url,
                duration, source_url, status, content
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            values = (
                douyin_id, unique_id, author, title, thumbnail_url,
                duration, source_url, 'pending', content_json
            )
            
            self.cursor.execute(sql, values)
            self.connection.commit()
            
            video_id = self.cursor.lastrowid
            db_logger.info(f"成功插入抖音视频记录: ID {video_id}, URL: {source_url}")
            return video_id
            
        except Exception as e:
            db_logger.error(f"插入抖音视频记录失败: {str(e)}")
            self.connection.rollback()
            return None

    def update_douyin_video_status(self, douyin_id, status, video_path=None, audio_path=None, 
                                 video_dir=None, audio_dir=None, error_message=None, audio_text=None):
        """更新抖音视频状态
        
        Args:
            douyin_id: 抖音视频ID
            status: 状态 (pending/downloading/completed/failed)
            video_path: 视频文件路径
            audio_path: 音频文件路径
            video_dir: 视频文件目录
            audio_dir: 音频文件目录
            error_message: 错误信息
            audio_text: 音频转写文本
            
        Returns:
            是否更新成功
        """
        try:
            update_fields = ["status = %s"]
            update_values = [status]
            
            if video_path is not None:
                update_fields.append("video_path = %s")
                update_values.append(video_path)
                
            if audio_path is not None:
                update_fields.append("audio_path = %s")
                update_values.append(audio_path)
                
            if video_dir is not None:
                update_fields.append("video_dir = %s")
                update_values.append(video_dir)
                
            if audio_dir is not None:
                update_fields.append("audio_dir = %s")
                update_values.append(audio_dir)
                
            if error_message is not None:
                update_fields.append("error_message = %s")
                update_values.append(error_message)
                
            if audio_text is not None:
                update_fields.append("audio_text = %s")
                update_values.append(audio_text)
            
            # 更新时间戳
            update_fields.append("updated_at = NOW()")
            
            # 构建SQL
            sql = f"""
            UPDATE douyin_video 
            SET {', '.join(update_fields)}
            WHERE douyin_id = %s
            """
            
            update_values.append(douyin_id)
            self.cursor.execute(sql, tuple(update_values))
            self.connection.commit()
            
            affected_rows = self.cursor.rowcount
            if affected_rows > 0:
                db_logger.info(f"更新抖音视频状态成功: ID {douyin_id}, 状态: {status}")
                return True
            else:
                db_logger.warning(f"未找到抖音视频记录: ID {douyin_id}")
                return False
                
        except Exception as e:
            db_logger.error(f"更新抖音视频状态失败: {str(e)}")
            self.connection.rollback()
            return False

    def get_douyin_video_by_id(self, douyin_id):
        """根据抖音ID获取视频信息
        
        Args:
            douyin_id: 抖音视频ID
            
        Returns:
            视频记录，如果不存在则返回None
        """
        try:
            sql = "SELECT * FROM douyin_video WHERE douyin_id = %s"
            self.cursor.execute(sql, (douyin_id,))
            result = self.cursor.fetchone()
            
            if result:
                db_logger.info(f"查询抖音视频成功: ID {douyin_id}")
            else:
                db_logger.warning(f"未找到抖音视频: ID {douyin_id}")
                
            return result
            
        except Exception as e:
            db_logger.error(f"查询抖音视频失败: {str(e)}")
            return None

    def get_douyin_video_by_url(self, url):
        """根据URL获取视频信息
        
        Args:
            url: 抖音视频URL
            
        Returns:
            视频记录，如果不存在则返回None
        """
        try:
            sql = "SELECT * FROM douyin_video WHERE source_url = %s"
            self.cursor.execute(sql, (url,))
            result = self.cursor.fetchone()
            
            if result:
                db_logger.info(f"查询抖音视频成功: URL {url}")
            else:
                db_logger.warning(f"未找到抖音视频: URL {url}")
                
            return result
            
        except Exception as e:
            db_logger.error(f"查询抖音视频失败: {str(e)}")
            return None

    def get_pending_douyin_videos(self, limit=10):
        """获取待下载的抖音视频列表
        
        Args:
            limit: 限制返回数量
            
        Returns:
            待下载视频列表
        """
        try:
            sql = """
            SELECT * FROM douyin_video 
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT %s
            """
            
            self.cursor.execute(sql, (limit,))
            results = self.cursor.fetchall()
            
            db_logger.info(f"查询待下载抖音视频: 返回 {len(results)} 条记录")
            return results
            
        except Exception as e:
            db_logger.error(f"查询待下载抖音视频失败: {str(e)}")
            return []
            
    def insert_douyin_video_novel(self, douyin_video_id, novel_id, novel_name, confidence=0, summary=""):
        """插入抖音视频与小说关联记录（支持多对多关联）
        
        Args:
            douyin_video_id: 抖音视频表ID
            novel_id: 小说表ID（可为空，AI未识别到时为NULL）
            novel_name: AI识别出的小说名称
            confidence: AI识别置信度
            summary: 关于该小说的内容描述
            
        Returns:
            记录ID，如果插入失败则返回None
        """
        try:
            # 检查是否已存在相同视频ID和小说名称的记录
            sql = "SELECT id FROM douyin_video_novel WHERE douyin_video_id = %s AND novel_name = %s"
            self.cursor.execute(sql, (douyin_video_id, novel_name))
            existing_record = self.cursor.fetchone()
            
            if existing_record:
                db_logger.info(f"已存在相同视频ID和小说名称的关联记录: 视频ID {douyin_video_id}, 小说 {novel_name}, 记录ID: {existing_record[0]}")
                return existing_record[0]
            
            # 准备插入数据
            sql = """
            INSERT INTO douyin_video_novel (
                douyin_video_id, novel_id, novel_name, confidence, summary
            ) VALUES (%s, %s, %s, %s, %s)
            """
            
            values = (
                douyin_video_id, novel_id, novel_name, confidence, summary
            )
            
            self.cursor.execute(sql, values)
            self.connection.commit()
            
            record_id = self.cursor.lastrowid
            db_logger.info(f"成功插入抖音视频与小说关联记录: ID {record_id}, 视频ID: {douyin_video_id}, 小说: {novel_name}")
            
            # 检查是否需要添加到待收录小说表
            if not novel_id:
                self.insert_to_do_novel(novel_name, douyin_video_id, summary)
            
            return record_id
            
        except Exception as e:
            db_logger.error(f"插入抖音视频与小说关联记录失败: {str(e)}")
            self.connection.rollback()
            return None
            
    def update_douyin_video_novel(self, id, novel_id=None, novel_name=None, confidence=None, summary=None):
        """更新抖音视频与小说关联记录
        
        Args:
            id: 关联记录ID
            novel_id: 小说表ID（可为空）
            novel_name: 小说名称
            confidence: AI识别置信度
            summary: 关于该小说的内容描述
            
        Returns:
            是否更新成功
        """
        try:
            update_fields = []
            update_values = []
            
            if novel_id is not None:
                update_fields.append("novel_id = %s")
                update_values.append(novel_id)
                
            if novel_name is not None:
                update_fields.append("novel_name = %s")
                update_values.append(novel_name)
                
            if confidence is not None:
                update_fields.append("confidence = %s")
                update_values.append(confidence)
                
            if summary is not None:
                update_fields.append("summary = %s")
                update_values.append(summary)
            
            # 如果没有要更新的字段，则直接返回
            if not update_fields:
                return False
                
            # 更新时间戳
            update_fields.append("updated_at = NOW()")
            
            # 构建SQL
            sql = f"""
            UPDATE douyin_video_novel 
            SET {', '.join(update_fields)}
            WHERE id = %s
            """
            
            update_values.append(id)
            self.cursor.execute(sql, tuple(update_values))
            self.connection.commit()
            
            affected_rows = self.cursor.rowcount
            if affected_rows > 0:
                db_logger.info(f"更新抖音视频与小说关联记录成功: ID {id}")
                return True
            else:
                db_logger.warning(f"未找到抖音视频与小说关联记录: ID {id}")
                return False
                
        except Exception as e:
            db_logger.error(f"更新抖音视频与小说关联记录失败: {str(e)}")
            self.connection.rollback()
            return False
            
    def get_douyin_video_novels_by_video_id(self, douyin_video_id):
        """根据抖音视频ID获取所有小说关联信息
        
        Args:
            douyin_video_id: 抖音视频表ID
            
        Returns:
            关联记录列表，如果不存在则返回空列表
        """
        try:
            sql = "SELECT * FROM douyin_video_novel WHERE douyin_video_id = %s"
            self.cursor.execute(sql, (douyin_video_id,))
            results = self.cursor.fetchall()
            
            db_logger.info(f"查询抖音视频与小说关联记录成功: 视频ID {douyin_video_id}, 匹配 {len(results)} 条记录")
            return results
            
        except Exception as e:
            db_logger.error(f"查询抖音视频与小说关联记录失败: {str(e)}")
            return []

    def get_all_novel_names(self, limit=100):
        """获取所有小说的名称列表
        
        Args:
            limit: 限制返回数量
            
        Returns:
            小说名称列表 [(id, title, author), ...]
        """
        try:
            sql = """
            SELECT id, title, author FROM novel
            ORDER BY title
            LIMIT %s
            """
            
            self.cursor.execute(sql, (limit,))
            results = self.cursor.fetchall()
            
            db_logger.info(f"查询小说名称列表: 返回 {len(results)} 条记录")
            return results
            
        except Exception as e:
            db_logger.error(f"查询小说名称列表失败: {str(e)}")
            return []

    def insert_novel(self, title, author="", description="", source_url="", category_id=1):
        """插入或更新小说数据
        
        Args:
            title: 小说标题（作为唯一标识）
            author: 作者
            description: 描述
            source_url: 来源URL
            category_id: 分类ID
        """
        # 检查是否已存在同名小说
        existing_novel = self.get_novel_by_title(title)
        
        if existing_novel:
            # 已存在，则更新非空字段
            update_fields = []
            update_values = []
            
            # 只更新非空的字段
            if author:
                update_fields.append("author = %s")
                update_values.append(author)
            if description:
                update_fields.append("description = %s")
                update_values.append(description)
            if source_url:
                update_fields.append("source_url = %s")
                update_values.append(source_url)
            if category_id:
                update_fields.append("category_id = %s")
                update_values.append(category_id)
            
            # 只有在有字段需要更新时才执行更新
            if update_fields:
                sql = f"""
                UPDATE novel 
                SET {', '.join(update_fields)}
                WHERE title = %s
                """
                update_values.append(title)
                self.cursor.execute(sql, tuple(update_values))
                self.connection.commit()
                
                db_logger.info(f"更新小说: {title} (ID: {existing_novel[0]})")
                # 返回现有记录ID
                return existing_novel[0]
        else:
            # 不存在，则插入新记录
            sql = """
            INSERT INTO novel (title, author, description, source_url, category_id, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            """
            self.cursor.execute(sql, (title, author, description, source_url, category_id))
            self.connection.commit()
            novel_id = self.cursor.lastrowid
            db_logger.info(f"新增小说: {title} (ID: {novel_id})")
            return novel_id

    def insert_chapter(self, novel_id, chapter_index, chapter_title="", 
                     chapter_url="", content_cn="", content_en="", 
                     summary_100="", summary="", 
                     outline_structured=None, storyboard_structured=None):
        """插入或更新章节数据到数据库
        
        Args:
            novel_id: 小说ID
            chapter_index: 章节索引
            chapter_title: 章节标题
            chapter_url: 章节URL
            content_cn: 中文内容
            content_en: 英文内容
            summary_100: 100字摘要
            summary: 完整摘要
            outline_structured: 结构化大纲(dict/json)
            storyboard_structured: 分镜建议(dict/json)
        """
        # 处理JSON字段
        outline_json = json.dumps(outline_structured, ensure_ascii=False) if outline_structured else '{}'
        storyboard_json = json.dumps(storyboard_structured, ensure_ascii=False) if storyboard_structured else '{}'
        
        # 检查是否已存在
        existing_chapter = self.get_chapter_by_novel_id_and_index(novel_id, chapter_index)
        
        if existing_chapter:
            # 更新已存在的章节，但保留非空字段
            update_fields = []
            update_values = []
            
            # 只更新非空/非None的字段
            if chapter_title: 
                update_fields.append("chapter_title = %s")
                update_values.append(chapter_title)
            if chapter_url:
                update_fields.append("chapter_url = %s")
                update_values.append(chapter_url)
            if content_cn:
                update_fields.append("content_cn = %s")
                update_values.append(content_cn)
            if content_en:
                update_fields.append("content_en = %s")
                update_values.append(content_en)
            if summary_100:
                update_fields.append("summary_100 = %s")
                update_values.append(summary_100)
            if summary:
                update_fields.append("summary = %s")
                update_values.append(summary)
            if outline_structured is not None:  # 允许空字典更新，但不允许None覆盖
                update_fields.append("outline_structured = %s")
                update_values.append(outline_json)
            if storyboard_structured is not None:  # 允许空字典更新，但不允许None覆盖
                update_fields.append("storyboard_structured = %s")
                update_values.append(storyboard_json)
            
            if update_fields:  # 只有当有字段需要更新时才执行更新
                sql = f"""
                UPDATE novel_chapter 
                SET {', '.join(update_fields)}
                WHERE novel_id = %s AND chapter_index = %s
                """
                update_values.extend([novel_id, chapter_index])
                self.cursor.execute(sql, tuple(update_values))
                self.connection.commit()
                
                content_size = len(content_cn) if content_cn else 0
                db_logger.info(f"更新章节: 小说ID {novel_id} - 第 {chapter_index+1} 章 - {chapter_title[:20]} (内容: {content_size} 字符)")
                
                return existing_chapter[0]  # 返回现有记录ID
        else:
            # 插入新记录
            sql = """
            INSERT INTO novel_chapter (
                novel_id, chapter_index, chapter_title, chapter_url,
                content_cn, content_en, summary_100, summary,
                outline_structured, storyboard_structured, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """
            
            self.cursor.execute(sql, (
                novel_id, chapter_index, chapter_title, chapter_url,
                content_cn, content_en, summary_100, summary,
                outline_json, storyboard_json
            ))
            
            self.connection.commit()
            chapter_id = self.cursor.lastrowid
            
            content_size = len(content_cn) if content_cn else 0
            db_logger.info(f"新增章节: 小说ID {novel_id} - 第 {chapter_index+1} 章 - {chapter_title[:20]} (内容: {content_size} 字符)")
            
            return chapter_id

    def get_novel_by_title(self, title):
        sql = "SELECT * FROM novel WHERE title = %s"
        self.cursor.execute(sql, (title,))
        return self.cursor.fetchone()

    def update_novel(self, novel_id, data):
        """更新小说信息
        
        Args:
            novel_id: 小说ID
            data: 要更新的数据字典 {字段名: 值}
        """
        if not data:
            return False
            
        # 构建更新SQL
        update_fields = []
        update_values = []
        
        for field, value in data.items():
            update_fields.append(f"{field} = %s")
            update_values.append(value)
        
        # 添加novel_id参数
        update_values.append(novel_id)
        
        # 执行更新
        sql = f"""
        UPDATE novel 
        SET {', '.join(update_fields)}
        WHERE id = %s
        """
        
        self.cursor.execute(sql, tuple(update_values))
        self.connection.commit()
        
        affected_rows = self.cursor.rowcount
        if affected_rows > 0:
            db_logger.info(f"更新小说信息: ID {novel_id} - 更新字段: {', '.join(data.keys())}")
        
        return affected_rows > 0

    def save_chapter(self, chapter_data):
        """保存章节数据到数据库，如果已存在则更新
        
        Args:
            chapter_data: 包含章节信息的字典
        """
        novel_id = chapter_data.get("novel_id")
        chapter_index = chapter_data.get("chapter_index")
        
        if not novel_id or chapter_index is None:
            db_logger.warning(f"保存章节数据失败: 缺少必要参数 novel_id={novel_id}, chapter_index={chapter_index}")
            return None
            
        # 检查是否已存在相同章节
        existing_chapter = self.get_chapter_by_novel_id_and_index(novel_id, chapter_index)
        
        # 确保字段名映射正确
        field_mapping = {
            "title": "chapter_title",
            "content": "content_cn",
            "url": "chapter_url",
            "is_complete": None,  # 忽略
            "word_count": None,   # 忽略
            "created_at": None,   # 忽略
        }
        
        # 处理字段名映射
        processed_data = {}
        for src_field, dest_field in field_mapping.items():
            if src_field in chapter_data and dest_field:
                processed_data[dest_field] = chapter_data[src_field]
        
        # 添加原始字段
        for field, value in chapter_data.items():
            if field not in field_mapping and field not in ["novel_id", "chapter_index"]:
                processed_data[field] = value
        
        if existing_chapter:
            # 构建更新SQL
            update_fields = []
            update_values = []
            
            for field, value in processed_data.items():
                update_fields.append(f"{field} = %s")
                update_values.append(value)
            
            # 添加条件参数
            update_values.append(novel_id)
            update_values.append(chapter_index)
            
            # 执行更新
            sql = f"""
            UPDATE novel_chapter 
            SET {', '.join(update_fields)}
            WHERE novel_id = %s AND chapter_index = %s
            """
            
            self.cursor.execute(sql, tuple(update_values))
            self.connection.commit()
            
            title = processed_data.get("chapter_title", "")
            content_size = len(processed_data.get("content_cn", ""))
            db_logger.info(f"更新现有章节: 小说ID {novel_id} - 第 {chapter_index+1} 章 - {title[:20]} (内容: {content_size} 字符)")
            
            return existing_chapter[0]  # 返回现有记录ID
        else:
            # 插入新章节
            chapter_id = self.insert_chapter(
                novel_id=novel_id,
                chapter_index=chapter_index,
                chapter_title=processed_data.get("chapter_title", ""),
                chapter_url=processed_data.get("chapter_url", ""),
                content_cn=processed_data.get("content_cn", ""),
                summary_100=processed_data.get("summary_100", ""),
                summary=processed_data.get("summary", "")
            )
            
            return chapter_id

    def get_chapter_by_novel_id_and_index(self, novel_id, chapter_index):
        sql = """
        SELECT * FROM novel_chapter 
        WHERE novel_id = %s AND chapter_index = %s
        """
        self.cursor.execute(sql, (novel_id, chapter_index))
        return self.cursor.fetchone()

    def get_all_novels(self, limit=100, offset=0):
        """获取所有小说的列表
        
        Args:
            limit: 限制返回数量
            offset: 偏移量
        
        Returns:
            小说列表
        """
        sql = """
        SELECT id, title, author, description, source_url, category_id, created_at
        FROM novel
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
        """
        self.cursor.execute(sql, (limit, offset))
        results = self.cursor.fetchall()
        db_logger.info(f"查询小说列表: 返回 {len(results)} 条记录")
        return results
    
    def get_novel_chapters(self, novel_id, limit=100, offset=0):
        """获取小说的所有章节
        
        Args:
            novel_id: 小说ID
            limit: 限制返回数量
            offset: 偏移量
        
        Returns:
            章节列表
        """
        sql = """
        SELECT id, novel_id, chapter_index, chapter_title, chapter_url, 
               created_at, summary_100, LENGTH(content_cn) as content_length
        FROM novel_chapter
        WHERE novel_id = %s
        ORDER BY chapter_index
        LIMIT %s OFFSET %s
        """
        self.cursor.execute(sql, (novel_id, limit, offset))
        results = self.cursor.fetchall()
        db_logger.info(f"查询小说章节: 小说ID {novel_id}, 返回 {len(results)} 章")
        return results
    
    def get_chapter_by_id(self, chapter_id):
        """根据ID获取章节详情
        
        Args:
            chapter_id: 章节ID
        
        Returns:
            章节详情
        """
        sql = """
        SELECT * FROM novel_chapter 
        WHERE id = %s
        """
        self.cursor.execute(sql, (chapter_id,))
        result = self.cursor.fetchone()
        if result:
            db_logger.info(f"查询章节详情: ID {chapter_id} 成功")
        else:
            db_logger.warning(f"查询章节详情: ID {chapter_id} 不存在")
        return result
    
    def get_novel_by_id(self, novel_id):
        """根据ID获取小说详情
        
        Args:
            novel_id: 小说ID
        
        Returns:
            小说详情
        """
        sql = "SELECT * FROM novel WHERE id = %s"
        self.cursor.execute(sql, (novel_id,))
        result = self.cursor.fetchone()
        if result:
            db_logger.info(f"查询小说详情: ID {novel_id} 成功")
        else:
            db_logger.warning(f"查询小说详情: ID {novel_id} 不存在")
        return result
    
    def count_novel_chapters(self, novel_id):
        """计算小说章节数量
        
        Args:
            novel_id: 小说ID
        
        Returns:
            章节数量
        """
        sql = "SELECT COUNT(*) FROM novel_chapter WHERE novel_id = %s"
        self.cursor.execute(sql, (novel_id,))
        result = self.cursor.fetchone()
        count = result[0] if result else 0
        db_logger.info(f"统计小说章节: 小说ID {novel_id}, 共 {count} 章")
        return count

    # === 待收录小说相关方法 ===
    
    def insert_to_do_novel(self, novel_name, douyin_video_id=None, recommendation_reason=""):
        """插入待收录小说记录
        
        Args:
            novel_name: 小说名称
            douyin_video_id: 抖音视频表ID
            recommendation_reason: 推荐原因（视频中的描述）
            
        Returns:
            记录ID，如果插入失败则返回None
        """
        try:
            # 检查是否已存在相同名称的记录
            sql = "SELECT id, status FROM to_do_novel WHERE novel_name = %s"
            self.cursor.execute(sql, (novel_name,))
            existing_record = self.cursor.fetchone()
            
            if existing_record:
                record_id = existing_record[0]
                status = existing_record[1]
                
                # 如果状态是pending，并且有新的推荐原因，则更新
                if status == 'pending' and recommendation_reason:
                    update_sql = """
                    UPDATE to_do_novel 
                    SET douyin_video_id = %s, recommendation_reason = %s, updated_at = NOW()
                    WHERE id = %s
                    """
                    self.cursor.execute(update_sql, (douyin_video_id, recommendation_reason, record_id))
                    self.connection.commit()
                    db_logger.info(f"更新待收录小说推荐原因: {novel_name}, ID: {record_id}")
                    
                db_logger.info(f"已存在待收录小说记录: {novel_name}, ID: {record_id}, 状态: {status}")
                return record_id
            
            # 准备插入数据
            sql = """
            INSERT INTO to_do_novel (
                novel_name, douyin_video_id, recommendation_reason, status
            ) VALUES (%s, %s, %s, %s)
            """
            
            values = (
                novel_name, douyin_video_id, recommendation_reason, 'pending'
            )
            
            self.cursor.execute(sql, values)
            self.connection.commit()
            
            record_id = self.cursor.lastrowid
            db_logger.info(f"成功插入待收录小说记录: ID {record_id}, 小说: {novel_name}")
            return record_id
            
        except Exception as e:
            db_logger.error(f"插入待收录小说记录失败: {str(e)}")
            self.connection.rollback()
            return None
    
    def update_to_do_novel_status(self, id, status, novel_id=None):
        """更新待收录小说状态
        
        Args:
            id: 待收录小说ID
            status: 状态 (pending/ignored/added)
            novel_id: 如果已添加，关联的小说ID
            
        Returns:
            是否更新成功
        """
        try:
            update_fields = ["status = %s"]
            update_values = [status]
            
            if novel_id is not None and status == 'added':
                # 如果状态是已添加，则记录关联的小说ID（可选）
                update_fields.append("novel_id = %s")
                update_values.append(novel_id)
            
            # 更新时间戳
            update_fields.append("updated_at = NOW()")
            
            # 构建SQL
            sql = f"""
            UPDATE to_do_novel 
            SET {', '.join(update_fields)}
            WHERE id = %s
            """
            
            update_values.append(id)
            self.cursor.execute(sql, tuple(update_values))
            self.connection.commit()
            
            affected_rows = self.cursor.rowcount
            if affected_rows > 0:
                db_logger.info(f"更新待收录小说状态成功: ID {id}, 状态: {status}")
                return True
            else:
                db_logger.warning(f"未找到待收录小说记录: ID {id}")
                return False
                
        except Exception as e:
            db_logger.error(f"更新待收录小说状态失败: {str(e)}")
            self.connection.rollback()
            return False
    
    def get_pending_to_do_novels(self, limit=100):
        """获取待处理的待收录小说列表
        
        Args:
            limit: 限制返回数量
            
        Returns:
            待处理小说列表
        """
        try:
            sql = """
            SELECT t.*, d.title as video_title, d.author as video_author
            FROM to_do_novel t
            LEFT JOIN douyin_video d ON t.douyin_video_id = d.id
            WHERE t.status = 'pending'
            ORDER BY t.created_at DESC
            LIMIT %s
            """
            
            self.cursor.execute(sql, (limit,))
            results = self.cursor.fetchall()
            
            db_logger.info(f"查询待处理小说列表: 返回 {len(results)} 条记录")
            return results
            
        except Exception as e:
            db_logger.error(f"查询待处理小说列表失败: {str(e)}")
            return []
            
    def get_to_do_novel_by_name(self, novel_name):
        """根据小说名称获取待收录小说记录
        
        Args:
            novel_name: 小说名称
            
        Returns:
            待收录小说记录，如果不存在则返回None
        """
        try:
            sql = """
            SELECT t.*, d.title as video_title, d.author as video_author
            FROM to_do_novel t
            LEFT JOIN douyin_video d ON t.douyin_video_id = d.id
            WHERE t.novel_name = %s
            """
            
            self.cursor.execute(sql, (novel_name,))
            result = self.cursor.fetchone()
            
            if result:
                db_logger.info(f"查询待收录小说成功: {novel_name}")
            else:
                db_logger.info(f"未找到待收录小说: {novel_name}")
                
            return result
            
        except Exception as e:
            db_logger.error(f"查询待收录小说失败: {str(e)}")
            return None 