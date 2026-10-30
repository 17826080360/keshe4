# -*- coding: utf-8 -*-
"""管理后台路由：数据看板、用户管理、商品审核、链上状态、篡改演示工具。"""
import json

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort

from database import db
from services import user_service, mall_service as ms, trace_service as ts
from blockchain.chain_backend import get_chain

bp = Blueprint("admin", __name__)


def _guard():
    if not g.user or g.user["role"] != "admin":
        abort(403)


@bp.route("/admin")
def dashboard():
    _guard()
    stats = {
        "users": user_service.count_users(),
        "batches": ts.count_batches(),
        "records": ts.count_records(),
        "onchain": ts.count_onchain(),
        "products": ms.count_products(),
        "orders": ms.count_orders(),
        "gmv": ms.sum_gmv(),
        "shipments": ms.count_shipments(),
    }
    chain = get_chain()
    integrity = chain.integrity_check()
    recent_records = db.query(
        "SELECT r.*, b.batch_code FROM records r JOIN batches b ON b.id = r.batch_id"
        " ORDER BY r.id DESC LIMIT 15")
    return render_template("admin/dashboard.html", stats=stats, chain=chain,
                           integrity=integrity, recent_records=recent_records)


@bp.route("/admin/users")
def users():
    _guard()
    rows = db.query("SELECT * FROM users ORDER BY id LIMIT 200")
    return render_template("admin/users.html", rows=rows)


@bp.route("/admin/users/<int:uid>/toggle", methods=["POST"])
def user_toggle(uid):
    _guard()
    u = user_service.find_user_by_id(uid)
    if not u:
        abort(404)
    new_status = "banned" if u["status"] == "active" else "active"
    db.execute("UPDATE users SET status = ? WHERE id = ?", (new_status, uid))
    flash(f"用户 {u['username']} 已{'禁用' if new_status=='banned' else '启用'}", "success")
    return redirect(url_for("admin.users"))


@bp.route("/admin/products")
def products():
    _guard()
    rows = db.query(
        "SELECT p.*, u.real_name seller_name FROM products p JOIN users u ON u.id = p.seller_id"
        " ORDER BY p.id DESC LIMIT 200")
    return render_template("admin/products.html", rows=rows)


@bp.route("/admin/products/<int:pid>/<status>", methods=["POST"])
def product_review(pid, status):
    _guard()
    if status not in ("on_sale", "off_sale", "rejected"):
        abort(400)
    ms.set_product_status(pid, status)
    flash(f"商品 {pid} 状态已更新为 {status}", "success")
    return redirect(url_for("admin.products"))


@bp.route("/admin/chain")
def chain_info():
    _guard()
    chain = get_chain()
    integrity = chain.integrity_check()
    records = db.query("SELECT * FROM records ORDER BY id DESC LIMIT 100")
    return render_template("admin/chain.html", chain=chain, integrity=integrity, records=records)


# ---------------------------------------------------------------------------
# 篡改演示：模拟攻击者直接改库，验证链上校验会拒绝
# ---------------------------------------------------------------------------
@bp.route("/admin/tamper", methods=["GET", "POST"])
def tamper():
    _guard()
    if request.method == "POST":
        rid = int(request.form.get("record_id", 0))
        field = request.form.get("field", "").strip()
        new_value = request.form.get("new_value", "").strip()
        rec = ts.get_record(rid)
        if not rec:
            flash("记录不存在", "error")
            return redirect(url_for("admin.tamper"))
        content = ts._parse_content(rec)
        if field not in content and field != "__all__":
            flash(f"字段「{field}」不存在于该记录内容中。可用字段：{list(content.keys())}", "error")
            return redirect(url_for("admin.tamper"))
        # 记录旧值留痕
        old_content = rec["content"]
        if field == "__all__":
            try:
                content = json.loads(new_value)
            except Exception:
                flash("新内容必须是合法 JSON", "error")
                return redirect(url_for("admin.tamper"))
        else:
            content[field] = new_value
        db.execute(
            "INSERT INTO tamper_logs(record_id,batch_id,record_type,old_content,new_content,operator)"
            " VALUES(?,?,?,?,?,?)",
            (rid, rec["batch_id"], rec["record_type"], old_content,
             json.dumps(content, ensure_ascii=False), g.user["username"]))
        # 篡改：更新库中明文，但保持原 data_hash 不变（攻击者未上链）
        db.execute("UPDATE records SET content = ? WHERE id = ?",
                   (json.dumps(content, ensure_ascii=False), rid))
        batch = ts.get_batch_by_id(rec["batch_id"])
        if batch:
            ts.invalidate_cache(batch["batch_code"])
        flash(f"已模拟篡改记录 #{rid}（{field}）。现在去扫码/溯源，链上校验将拒绝该记录。", "success")
        return redirect(url_for("admin.tamper"))

    records = db.query(
        "SELECT r.*, b.batch_code FROM records r JOIN batches b ON b.id = r.batch_id"
        " ORDER BY r.id DESC LIMIT 40")
    logs = db.query("SELECT * FROM tamper_logs ORDER BY id DESC LIMIT 20")
    return render_template("admin/tamper.html", records=records, logs=logs)


@bp.route("/admin/tamper/<int:rid>/restore", methods=["POST"])
def tamper_restore(rid):
    """从篡改日志恢复记录原文（演示用），恢复后校验重新通过。"""
    _guard()
    log = db.query(
        "SELECT * FROM tamper_logs WHERE record_id = ? ORDER BY id DESC LIMIT 1", (rid,), one=True)
    if not log:
        flash("未找到该记录的篡改日志", "error")
        return redirect(url_for("admin.tamper"))
    db.execute("UPDATE records SET content = ? WHERE id = ?", (log["old_content"], rid))
    batch = ts.get_batch_by_id(log["batch_id"])
    if batch:
        ts.invalidate_cache(batch["batch_code"])
    flash(f"记录 #{rid} 已恢复原文，校验将重新通过", "success")
    return redirect(url_for("admin.tamper"))


@bp.route("/admin/reset_demo", methods=["POST"])
def reset_demo():
    """一键重建演示数据（清空并重新初始化数据库与链）。"""
    _guard()
    import subprocess, sys
    from database import db as dbm
    conn = dbm.get_conn()
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for t in tables:
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
    conn.close()
    # 重置链
    chain = get_chain()
    chain.local.blocks = []
    chain.local._save()
    from database.seed import seed_all
    seed_all()
    flash("演示数据已重置", "success")
    return redirect(url_for("admin.dashboard"))
