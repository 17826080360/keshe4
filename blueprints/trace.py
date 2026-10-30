# -*- coding: utf-8 -*-
"""溯源路由：扫码查询、溯源报告（含缓存与篡改检测）。

业务规则：溯源查询需要登录。未登录访问会跳转登录页，
登录成功后自动返回原溯源地址（?next= 回跳）。
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort

from services import trace_service as ts

bp = Blueprint("trace", __name__)


def _require_login(next_url):
    """未登录 → 跳转登录页，并携带回跳地址。"""
    if not g.user:
        flash("溯源查询需要登录，请先登录", "error")
        return redirect(url_for("auth.login", next=next_url))
    return None


@bp.route("/trace")
def query():
    """扫码/输入溯源码查询入口（需登录）。"""
    r = _require_login("/trace")
    if r:
        return r
    samples = ts.list_batches(limit=3)
    return render_template("trace/query.html", samples=samples)


@bp.route("/trace/<code>")
def report(code):
    """溯源报告（需登录）。"""
    r = _require_login(f"/trace/{code}")
    if r:
        return r
    fresh = request.args.get("fresh") == "1"
    data = ts.build_report(code, fresh=fresh)
    if not data:
        abort(404, description="溯源码不存在")
    return render_template("trace/report.html", data=data, code=code)


@bp.route("/trace/code/<int:rid>")
def by_record(rid):
    """通过记录跳转批次（需登录）。"""
    r = _require_login(f"/trace/code/{rid}")
    if r:
        return r
    rec = ts.get_record(rid)
    if not rec:
        abort(404)
    batch = ts.get_batch_by_id(rec["batch_id"])
    return report(batch["batch_code"])
