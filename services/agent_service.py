# -*- coding: utf-8 -*-
"""
溯源智能助手（任务型 Agent）。

设计：用户用自然语言提问 → 意图识别 → 调用已有的内部工具
（溯源报告 / 冷链温度 / 防篡改校验 / 在售商品 / 我的订单）→ 组织成自然语言回答。
每个回答都返回本次调用了哪些工具、按什么顺序，便于答辩时展示“Agent 调用工具”。
"""
import re
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import trace_service as ts
from services import mall_service as ms
from services import llm_service

BATCH_CODE_RE = re.compile(r"TRC\d+")

STAGE_CN = {
    "farming": "养殖", "processing": "加工",
    "logistics": "物流", "retail": "零售", "sale": "销售",
}


def _find_batch(question):
    """从问题里定位批次：先找 TRC 溯源码，再按产品名模糊匹配。"""
    m = BATCH_CODE_RE.search(question.upper())
    if m:
        b = ts.get_batch_by_code(m.group())
        if b:
            return b
    # 1) 产品名整名出现在问题里
    for b in ts.list_batches(limit=80):
        if b["product_name"] and b["product_name"] in question:
            return b
    # 2) 按共享汉字数模糊命中（如“这批鱼” → 清江鲈鱼），停用常见虚词
    STOP = set("有的这我你他她它们是在和与及了吗呢吧啊呀有没有怎么这个那个一批"
               "温断链冷售买商品物订单货")
    def score(b):
        name = b["product_name"] or ""
        return sum(1 for ch in set(name)
                   if ch in question and "一" <= ch <= "鿿" and ch not in STOP)
    rows = ts.list_batches(limit=80)
    best = max(rows, key=score, default=None)
    if best and score(best) >= 1:
        return best
    return None


def tool_trace_report(batch):
    """工具：生成某批次完整溯源报告并汇总。"""
    rep = ts.build_report(batch["batch_code"], fresh=True)
    temps, stages_seen = [], set()
    for t in rep["timeline"]:
        stages_seen.add(t["stage_type"])
        if t["record"]["record_type"] == "temperature":
            try:
                temps.append(float(t["content"].get("temperature")))
            except (TypeError, ValueError):
                pass
    lines = [
        f"批次 {batch['batch_code']}：{batch['product_name']}（{batch['origin']}），共 {len(rep['timeline'])} 条记录。",
        ("链上校验：全部通过，数据未被篡改。" if rep["ok"]
         else f"链上校验：发现 {rep['bad_count']} 条异常，已标红，请勿食用并联系平台。"),
    ]
    if temps:
        lines.append(f"冷链温度区间 {min(temps):.1f}℃ ~ {max(temps):.1f}℃。")
    lines.append("已覆盖环节：" + "、".join(STAGE_CN.get(s, s) for s in stages_seen) + "。")
    return "\n".join(lines)


def tool_cold_chain(batch):
    """工具：分析冷链温度是否正常、有无断链。"""
    rep = ts.build_report(batch["batch_code"])
    temps = []
    for t in rep["timeline"]:
        if t["record"]["record_type"] == "temperature":
            v = t["content"].get("temperature")
            loc = t["content"].get("location", "")
            temps.append((v, loc))
    if not temps:
        return "该批次暂无冷链温度记录。"
    vals = [float(v) for v, _ in temps if v is not None]
    line = f"该批次共上报 {len(temps)} 次冷链温度，区间 {min(vals):.1f}℃ ~ {max(vals):.1f}℃。"
    bad = [(v, loc) for v, loc in temps if v is not None and float(v) > -10]
    if bad:
        line += f" 注意：有 {len(bad)} 次高于冷链标准（如 {bad[0][1]} {bad[0][0]}℃），疑似断链。"
    else:
        line += " 温度全程正常，未发现断链。"
    return line


def tool_explain_verify():
    """工具：解释防篡改原理。"""
    return ("防篡改原理：每录入一条记录，系统先把内容算成 SHA-256 指纹并写入区块链，"
            "明文只存在数据库。扫码时重新计算指纹并与链上比对——"
            "只要改过任何一个字，指纹都会变，当场暴露。你可以直接问我校验某个批次。")


def tool_products(question):
    """工具：查询在售商品。"""
    rows = ms.list_products(keyword=question, status="on_sale")
    if not rows:
        rows = ms.list_products(status="on_sale")
    rows = rows[:5]
    if not rows:
        return "当前没有在售商品。"
    out = ["在售商品："]
    for p in rows:
        out.append(f"· {p['title']}  ¥{p['price']}/{p['unit']}（卖家：{p['seller_name']}）")
    return "\n".join(out)


def tool_my_orders(user):
    """工具：查询当前用户的订单。"""
    if not user:
        return "请先登录，再查询我的订单。"
    rows = ms.list_orders(user["id"], side="buy")[:5]
    if not rows:
        return "你还没有订单。"
    out = ["最近订单："]
    for o in rows:
        out.append(f"· {o['order_no']}  ¥{o['total_amount']}  状态：{o['status']}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# LLM function-calling（DeepSeek）
# ---------------------------------------------------------------------------
TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "trace_report",
        "description": "查询某农产品批次的完整溯源报告：养殖/加工/物流/零售/销售全过程记录、链上是否被篡改、冷链温度区间。用户给出产品名或 TRC 溯源码时调用。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "产品名或溯源码，如 清江鲈鱼 / TRC2026..."}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "cold_chain",
        "description": "查询某批次冷链温度是否正常、有无断链。用户问冷链、温度、会不会坏时调用。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "产品名或溯源码"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "explain_verify",
        "description": "解释区块链如何防篡改（SHA-256 指纹 + 链上比对原理）。用户问原理、为什么可信时调用。",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "list_products",
        "description": "查询商城在售商品（可按关键词）。用户问有什么在卖、价格、想购买时调用。",
        "parameters": {"type": "object", "properties": {
            "keyword": {"type": "string", "description": "可选关键词"}}}}},
    {"type": "function", "function": {
        "name": "my_orders",
        "description": "查询当前登录用户的购买订单及状态。",
        "parameters": {"type": "object", "properties": {}}}},
]

SYSTEM_PROMPT = (
    "你是「安心溯源商城」的智能助手，服务一个农产品溯源区块链系统。"
    "你的职责是用中文、口语化、简洁地回答用户，并在需要事实数据时调用提供的工具。"
    "不要编造批次号、温度、订单号；不确定就调用工具。一次回答一般不超过4句话。"
)


def _exec_tool(name, args, user):
    """按工具名执行内部函数，返回(文本结果, 展示步骤)。"""
    if name == "trace_report":
        b = _find_batch(args.get("query", ""))
        if not b:
            return "没找到对应批次，请给出产品名或 TRC 溯源码。", "trace_report（未定位到批次）"
        return tool_trace_report(b), f"trace_report → {b['batch_code']}"
    if name == "cold_chain":
        b = _find_batch(args.get("query", ""))
        if not b:
            return "没找到对应批次。", "cold_chain（未定位到批次）"
        return tool_cold_chain(b), f"cold_chain → {b['batch_code']}"
    if name == "explain_verify":
        return tool_explain_verify(), "explain_verify"
    if name == "list_products":
        return tool_products(args.get("keyword", "")), "list_products"
    if name == "my_orders":
        return tool_my_orders(user), "my_orders"
    return "未知工具。", name


def _run_llm(question, user):
    """大模型 function-calling 主循环。"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    steps, used = [], []
    msg = llm_service.chat(messages, tools=TOOL_SCHEMAS)
    for _ in range(3):  # 最多 3 轮工具调用，防止死循环
        if not msg.get("tool_calls"):
            break
        messages.append(msg)
        for call in msg["tool_calls"]:
            fn = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result, step = _exec_tool(fn, args, user)
            used.append(fn)
            steps.append(f"大模型决策 → 调用 {step}")
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
        msg = llm_service.chat(messages, tools=TOOL_SCHEMAS)
    reply = (msg.get("content") or "").strip() or "（模型未返回内容）"
    steps.append("大模型生成最终自然语言回答")
    return {"reply": reply, "steps": steps, "tools": used, "mode": "llm"}


def _run_rules(question, user=None):
    """规则版兜底（断网/大模型不可用时仍可用）。"""
    q = question.strip()
    steps, used = [], []

    if any(k in q for k in ["你能做", "帮助", "怎么用", "功能", "你会什么"]):
        used.append("help")
        steps.append("规则：能力咨询 → help")
        return {
            "reply":
                "我是溯源智能助手，可以帮你：\n"
                "· 查某批次溯源：『查一下 TRC…』或『鲈鱼的溯源』\n"
                "· 查冷链：『这批鱼冷链有没有断』\n"
                "· 校验防篡改：『校验这个批次有没有被改』\n"
                "· 查在售商品：『有什么在卖』\n"
                "· 查我的订单：『我的订单怎么样了』",
            "steps": steps, "tools": used, "mode": "rules",
        }

    batch = _find_batch(q)

    if batch and any(k in q for k in ["冷链", "温度", "断链", "断了"]):
        used.append("cold_chain")
        steps.append(f"规则：冷链 → {batch['batch_code']} → cold_chain")
        return {"reply": tool_cold_chain(batch), "steps": steps, "tools": used, "mode": "rules"}

    if batch and any(k in q for k in ["校验", "篡改", "真伪", "真的假", "安全吗"]):
        used.append("verify")
        steps.append(f"规则：校验 → {batch['batch_code']} → trace_report")
        return {"reply": tool_trace_report(batch), "steps": steps, "tools": used, "mode": "rules"}

    if batch:
        used.append("trace_report")
        steps.append(f"规则：溯源 → {batch['batch_code']} → trace_report")
        return {"reply": tool_trace_report(batch), "steps": steps, "tools": used, "mode": "rules"}

    if any(k in q for k in ["订单", "买到", "我的", "付款"]):
        used.append("my_orders")
        steps.append("规则：我的订单 → my_orders")
        return {"reply": tool_my_orders(user), "steps": steps, "tools": used, "mode": "rules"}

    if any(k in q for k in ["商品", "卖", "菜", "鱼", "价格", "买", "有什么"]):
        used.append("list_products")
        steps.append("规则：在售商品 → list_products")
        return {"reply": tool_products(q), "steps": steps, "tools": used, "mode": "rules"}

    if any(k in q for k in ["篡改", "防", "区块链", "原理", "为什么"]):
        used.append("explain_verify")
        steps.append("规则：原理解释 → explain_verify")
        return {"reply": tool_explain_verify(), "steps": steps, "tools": used, "mode": "rules"}

    rows = ts.list_batches(limit=5)
    used.append("list_batches(fallback)")
    steps.append("未命中意图 → 兜底列出最近批次")
    lines = ["没太明白，你可以换个说法，例如："]
    lines += [f"· 查一下 {b['product_name']}（{b['batch_code']}）" for b in rows]
    return {"reply": "\n".join(lines), "steps": steps, "tools": used, "mode": "rules"}


def run(question, user=None):
    """Agent 主入口：优先 DeepSeek 大模型 function-calling，失败回退规则版。"""
    try:
        return _run_llm(question, user)
    except Exception as e:  # 断网 / key 失效 / 限流等
        result = _run_rules(question, user)
        result["steps"].append(f"⚠️ 大模型不可用（{type(e).__name__}），已回退规则版")
        return result
