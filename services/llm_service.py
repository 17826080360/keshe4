# -*- coding: utf-8 -*-
"""
DeepSeek 大模型调用层（OpenAI 兼容接口）。
失败（断网/限流）时调用方应回退到规则版助手。
"""
import json
import requests

import os
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE = "https://api.deepseek.com"
MODEL = "deepseek-chat"

TIMEOUT = 40


def chat(messages, tools=None, temperature=0.2):
    """调用 DeepSeek chat/completions，返回 choices[0].message 字典。"""
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    resp = requests.post(f"{DEEPSEEK_BASE}/chat/completions",
                         headers=headers, json=payload, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]
