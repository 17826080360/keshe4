# -*- coding: utf-8 -*-
"""
农产品溯源区块链系统 + 安心商城
================================
运行：python app.py  →  http://127.0.0.1:5000

技术栈：Flask + SQLite（明文分层存储） + 哈希上链（Ganache 以太坊 / 本地模拟链）
        + Redis/内存缓存（扫码高并发）
"""
import os

from flask import Flask, render_template, session, g, redirect, url_for

from database import db
from database.seed import ensure_seeded
from services import user_service
from blockchain.chain_backend import get_chain


def create_app():
    app = Flask(__name__)
    app.secret_key = "agri-trace-secret-2026"
    app.config["JSON_AS_ASCII"] = False

    # 初始化数据库与演示数据
    db.init_db()
    ensure_seeded()

    # 注册蓝图
    from blueprints import auth, trace, mall, panel, admin, agent
    app.register_blueprint(auth.bp)
    app.register_blueprint(trace.bp)
    app.register_blueprint(mall.bp)
    app.register_blueprint(panel.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(agent.bp)

    # ---------- 上下文 ----------
    @app.before_request
    def load_user():
        uid = session.get("uid")
        g.user = user_service.find_user_by_id(uid) if uid else None

    @app.context_processor
    def inject_globals():
        role_names = user_service.ROLE_NAMES
        return {
            "role_names": role_names,
            "ROLE_ICONS": user_service.ROLE_ICONS,
            "chain_name": get_chain().chain_name(),
            "PLATFORM_FEE": 0.02,
        }

    # ---------- 首页 ----------
    @app.route("/")
    def index():
        from services import mall_service as m
        products = m.list_products()
        stats = {
            "batches": db.query("SELECT COUNT(*) c FROM batches", one=True)["c"],
            "records": db.query("SELECT COUNT(*) c FROM records", one=True)["c"],
            "products": db.query("SELECT COUNT(*) c FROM products WHERE status='on_sale'", one=True)["c"],
            "orders": db.query("SELECT COUNT(*) c FROM orders", one=True)["c"],
        }
        return render_template("index.html", products=products, stats=stats)

    # ---------- 错误处理 ----------
    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, msg=getattr(e, "description", "页面不存在")), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", code=403, msg="没有权限访问该页面"), 403

    return app


app = create_app()

if __name__ == "__main__":
    print("=" * 62)
    print("  农产品溯源区块链系统 · 安心商城")
    print("  访问地址：http://127.0.0.1:5000")
    print("  演示账号：admin / farmer1 / contractor1 / logistics1 / retailer1 / consumer1")
    print("  默认密码：123456")
    print("=" * 62)
    app.run(host="127.0.0.1", port=5000, debug=False)
