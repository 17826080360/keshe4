# -*- coding: utf-8 -*-
"""用户认证与钱包服务。"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import db
from werkzeug.security import generate_password_hash, check_password_hash

ROLE_NAMES = {
    "farmer": "农户",
    "contractor": "加工商",
    "logistics": "物流公司",
    "retailer": "零售商",
    "consumer": "消费者",
    "admin": "平台管理员",
}

ROLE_ICONS = {
    "farmer": "👨‍🌾",
    "contractor": "🏭",
    "logistics": "🚚",
    "retailer": "🏪",
    "consumer": "🛒",
    "admin": "🛡️",
}

# 演示账号（种子数据创建，密码统一 123456）
DEMO_ACCOUNTS = [
    ("farmer1", "farmer", "王大海", "养殖户·青山鱼塘"),
    ("contractor1", "contractor", "陈师傅", "鲜品水产加工厂"),
    ("logistics1", "logistics", "刘司机", "冷链速运"),
    ("retailer1", "retailer", "赵老板", "鲜到家超市"),
    ("consumer1", "consumer", "小李", "普通消费者"),
    ("admin", "admin", "系统管理员", "平台运营"),
]


def find_user(username):
    return db.query("SELECT * FROM users WHERE username = ?", (username,), one=True)


def find_user_by_id(uid):
    return db.query("SELECT * FROM users WHERE id = ?", (uid,), one=True)


def register(username, password, role, real_name, phone, company, address):
    if find_user(username):
        return None, "用户名已存在"
    if role not in ROLE_NAMES:
        return None, "非法的角色"
    uid = db.execute(
        "INSERT INTO users(username,password_hash,role,real_name,phone,company,address,balance)"
        " VALUES(?,?,?,?,?,?,?,10000)",
        (username, generate_password_hash(password), role, real_name, phone, company, address),
        fetch_id=True,
    )
    return find_user_by_id(uid), None


def check_login(username, password):
    u = find_user(username)
    if not u or not check_password_hash(u["password_hash"], password):
        return None
    if u["status"] != "active":
        return None
    return u


def wallet_balance(uid):
    u = find_user_by_id(uid)
    return u["balance"] if u else 0


def recharge(uid, amount, remark="模拟充值"):
    u = find_user_by_id(uid)
    new_bal = round(u["balance"] + amount, 2)
    db.execute("UPDATE users SET balance = ? WHERE id = ?", (new_bal, uid))
    db.execute(
        "INSERT INTO wallet_transactions(user_id,amount,balance_after,tx_type,related_order,remark)"
        " VALUES(?,?,?,?,?,?)",
        (uid, round(amount, 2), new_bal, "recharge", None, remark),
    )
    return new_bal


def transfer(from_uid, to_uid, amount, tx_type, related_order, remark):
    """转账：从 from_uid 扣款，给 to_uid 入账，各记一条流水。"""
    from_u = find_user_by_id(from_uid)
    if from_u["balance"] + 1e-6 < amount:
        return False, "余额不足"
    new_from = round(from_u["balance"] - amount, 2)
    db.execute("UPDATE users SET balance = ? WHERE id = ?", (new_from, from_uid))
    db.execute(
        "INSERT INTO wallet_transactions(user_id,amount,balance_after,tx_type,related_order,remark)"
        " VALUES(?,?,?,?,?,?)",
        (from_uid, round(-amount, 2), new_from, tx_type, related_order, remark),
    )
    if to_uid:
        to_u = find_user_by_id(to_uid)
        new_to = round(to_u["balance"] + amount, 2)
        db.execute("UPDATE users SET balance = ? WHERE id = ?", (new_to, to_uid))
        db.execute(
            "INSERT INTO wallet_transactions(user_id,amount,balance_after,tx_type,related_order,remark)"
            " VALUES(?,?,?,?,?,?)",
            (to_uid, round(amount, 2), new_to, tx_type, related_order, remark),
        )
    return True, None


def list_transactions(uid, limit=50):
    return db.query(
        "SELECT * FROM wallet_transactions WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (uid, limit),
    )


def count_users():
    return db.query("SELECT COUNT(*) c FROM users", one=True)["c"]
