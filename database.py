import mysql.connector
from config import DB_CONFIG

class Database:
    def __init__(self):
        self.connection = mysql.connector.connect(**DB_CONFIG)
        self.cursor = self.connection.cursor()

    def close(self):
        self.cursor.close()
        self.connection.close()

    def insert_novel(self, title, author, description, source_url, category_id):
        sql = """
        INSERT INTO novel (title, author, description, source_url, category_id)
        VALUES (%s, %s, %s, %s, %s)
        """
        self.cursor.execute(sql, (title, author, description, source_url, category_id))
        self.connection.commit()
        return self.cursor.lastrowid

    def insert_chapter(self, novel_id, chapter_index, chapter_title, 
                      chapter_summary, chapter_content_cn, 
                      chapter_content_en, chapter_url):
        sql = """
        INSERT INTO novel_chapter (novel_id, chapter_index, chapter_title,
                                 chapter_summary, chapter_content_cn,
                                 chapter_content_en, chapter_url)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        self.cursor.execute(sql, (novel_id, chapter_index, chapter_title,
                                chapter_summary, chapter_content_cn,
                                chapter_content_en, chapter_url))
        self.connection.commit()
        return self.cursor.lastrowid

    def get_novel_by_title(self, title):
        sql = "SELECT * FROM novel WHERE title = %s"
        self.cursor.execute(sql, (title,))
        return self.cursor.fetchone()

    def get_chapter_by_novel_id_and_index(self, novel_id, chapter_index):
        sql = """
        SELECT * FROM novel_chapter 
        WHERE novel_id = %s AND chapter_index = %s
        """
        self.cursor.execute(sql, (novel_id, chapter_index))
        return self.cursor.fetchone() 