# -*- coding: utf-8 -*-
"""认证与钱包路由。"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g

from services import user_service

bp = Blueprint("auth", __name__)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "consumer")
        real_name = request.form.get("real_name", "").strip()
        phone = request.form.get("phone", "").strip()
        company = request.form.get("company", "").strip()
        address = request.form.get("address", "").strip()
        if not username or not password or not real_name:
            flash("用户名、密码、姓名不能为空", "error")
            return redirect(url_for("auth.register"))
        u, err = user_service.register(username, password, role, real_name, phone, company, address)
        if err:
            flash(err, "error")
            return redirect(url_for("auth.register"))
        session["uid"] = u["id"]
        flash(f"注册成功，欢迎 {u['real_name']}！初始钱包余额 10000 元（演示）。", "success")
        return redirect(url_for("index"))
    return render_template("auth/register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.args.get("next") or request.form.get("next") or ""
    if next_url and not next_url.startswith("/"):
        next_url = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        u = user_service.check_login(username, password)
        if not u:
            flash("用户名或密码错误", "error")
            return redirect(url_for("auth.login", next=next_url or None))
        session["uid"] = u["id"]
        flash(f"欢迎回来，{u['real_name']}！", "success")
        if next_url:
            return redirect(next_url)
        return redirect(url_for("index"))
    return render_template("auth/login.html", next_url=next_url)


@bp.route("/logout")
def logout():
    session.clear()
    flash("已退出登录", "success")
    return redirect(url_for("index"))


@bp.route("/wallet", methods=["GET", "POST"])
def wallet():
    user = g.user
    if request.method == "POST":
        amount = float(request.form.get("amount", 0))
        if amount <= 0 or amount > 1000000:
            flash("充值金额需在 0 ~ 1000000 之间", "error")
        else:
            new_bal = user_service.recharge(user["id"], amount)
            flash(f"充值成功，当前余额 {new_bal:,.2f} 元（模拟支付，不产生真实扣款）", "success")
        return redirect(url_for("auth.wallet"))
    txs = user_service.list_transactions(user["id"])
    return render_template("wallet.html", txs=txs)
