# -*- coding: utf-8 -*-
"""数据库连接与初始化。使用 MySQL。"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor"))
import pymysql
from pymysql.cursors import DictCursor

DB_CONFIG = dict(
    host="127.0.0.1",
    port=3306,
    user="root",
    password="123456",
    charset="utf8mb4",
    cursorclass=DictCursor,
    autocommit=False,
)
DB_NAME = "agri_trace"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema_mysql.sql")


def _conn(use_db=True):
    cfg = dict(DB_CONFIG)
    if use_db:
        cfg["database"] = DB_NAME
    return pymysql.connect(**cfg)


def init_db():
    # 建库
    root = pymysql.connect(host=DB_CONFIG["host"], port=DB_CONFIG["port"],
                           user=DB_CONFIG["user"], password=DB_CONFIG["password"],
                           charset="utf8mb4")
    try:
        cur = root.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME} DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci")
        root.commit()
    finally:
        root.close()
    # 建表
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        sql = f.read()
    conn = _conn()
    try:
        cur = conn.cursor()
        for chunk in sql.split(";"):
            lines = [ln for ln in chunk.splitlines() if not ln.strip().startswith("--")]
            stmt = "\n".join(lines).strip()
            if stmt:
                cur.execute(stmt)
        conn.commit()
    finally:
        conn.close()


def _convert(sql):
    # SQLite 占位符 ? 转 MySQL %s；SQLite 时间函数转 MySQL
    return sql.replace("datetime('now','localtime')", "NOW()").replace("?", "%s")


def query(sql, args=(), one=False):
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(_convert(sql), args)
        rows = cur.fetchall()
        return (rows[0] if rows else None) if one else rows
    finally:
        conn.close()


def execute(sql, args=(), fetch_id=False):
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(_convert(sql), args)
        conn.commit()
        return cur.lastrowid if fetch_id else cur.rowcount
    finally:
        conn.close()


def executemany(sql, args_list):
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.executemany(_convert(sql), args_list)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
