# db_manager.py
# -*- coding: utf-8 -*-

import sqlite3
import datetime
import os


class DBManager:
    def __init__(self, db_name="stock_data.db"):
        # 自动初始化数据库
        self.db_name = db_name
        self.init_db()

    def get_conn(self):
        return sqlite3.connect(self.db_name)

    def init_db(self):
        """初始化表结构"""
        conn = self.get_conn()
        c = conn.cursor()

        # 1. 创建【市场情绪表】 (Market Mood)
        # 记录每天的 大盘涨幅 和 昨板溢价
        c.execute('''
            CREATE TABLE IF NOT EXISTS market_mood (
                date TEXT PRIMARY KEY,
                sh_index_pct REAL,
                zt_premium REAL,
                mood_level INTEGER
            )
        ''')

        # 2. 创建【选股记录表】 (Candidates)
        # 记录脚本选出的每一只票，方便后续回测
        c.execute('''
            CREATE TABLE IF NOT EXISTS stock_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                code TEXT,
                name TEXT,
                strategy TEXT,
                concept TEXT,
                price REAL,
                pct REAL,
                timestamp TEXT
            )
        ''')

        conn.commit()
        conn.close()

    def save_mood(self, date, sh_pct, zt_premium, mood_level):
        """保存当日情绪 (如果当日已存在则覆盖)"""
        conn = self.get_conn()
        c = conn.cursor()
        try:
            c.execute('''
                INSERT OR REPLACE INTO market_mood (date, sh_index_pct, zt_premium, mood_level)
                VALUES (?, ?, ?, ?)
            ''', (date, sh_pct, zt_premium, mood_level))
            conn.commit()
            # print(f"💾 [DB] 情绪数据已保存: {date}")
        except Exception as e:
            print(f"❌ [DB] 保存情绪失败: {e}")
        finally:
            conn.close()

    def save_candidate(self, date, code, name, strategy, concept, price, pct):
        """保存选出的股票"""
        conn = self.get_conn()
        c = conn.cursor()
        try:
            now_time = datetime.datetime.now().strftime("%H:%M:%S")
            c.execute('''
                INSERT INTO stock_candidates (date, code, name, strategy, concept, price, pct, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (date, code, name, strategy, concept, price, pct, now_time))
            conn.commit()
        except Exception as e:
            print(f"❌ [DB] 保存个股失败: {e}")
        finally:
            conn.close()

    def export_to_excel(self):
        """(可选) 将数据库导出为 Excel 方便查看"""
        import pandas as pd
        conn = self.get_conn()
        try:
            df = pd.read_sql_query("SELECT * FROM stock_candidates ORDER BY date DESC, timestamp DESC", conn)
            df.to_excel("选股记录复盘.xlsx", index=False)
            print("✅ 已导出为 '选股记录复盘.xlsx'")
        except Exception as e:
            print(f"导出失败: {e}")
        finally:
            conn.close()


# 测试用
if __name__ == "__main__":
    db = DBManager()
    print("数据库初始化完成。")