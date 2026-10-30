# -*- coding: utf-8 -*-
"""智能助手（Agent）路由：聊天页面 + 对话接口。"""
from flask import Blueprint, render_template, request, jsonify, g, redirect, url_for

from services import agent_service

bp = Blueprint("assistant", __name__, url_prefix="/assistant")


@bp.route("")
def home():
    if not g.user:
        return redirect(url_for("auth.login", next="/assistant"))
    return render_template("assistant.html")


@bp.route("/api/chat", methods=["POST"])
def chat():
    if not g.user:
        return jsonify({"error": "请先登录"}), 401
    msg = (request.get_json(silent=True) or {}).get("message", "")
    if not msg.strip():
        return jsonify({"reply": "请输入你的问题。", "steps": [], "tools": []})
    result = agent_service.run(msg, g.user)
    return jsonify(result)
