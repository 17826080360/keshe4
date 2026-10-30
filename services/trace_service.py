# -*- coding: utf-8 -*-
"""
溯源核心服务：批次-环节-记录三层模型 + 哈希上链 + 篡改校验。

设计要点：
  - 明文存 SQLite，指纹（SHA-256）上链 → 分层存储；
  - 同批次记录按序哈希链接（prev_hash），链上与库中双重校验；
  - 扫码查询走 Redis/内存缓存，未命中才回源组装。
"""
import json
import random
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import db
from blockchain.chain_backend import get_chain
from blockchain.hash_utils import content_hash
from services.cache_service import cache

# 记录类型 → 所属环节
RECORD_STAGE = {
    "seed": "farming", "feed": "farming", "fertilize": "farming",
    "medicine": "farming", "water": "farming", "harvest": "farming",
    "warehouse": "processing", "process": "processing", "package": "processing",
    "temperature": "logistics", "track": "logistics", "ship": "logistics",
    "list": "retail",
    "sale": "sale",
}

STAGE_META = {
    "farming": ("🌱", "种植/养殖环节", "farming"),
    "processing": ("🏭", "加工环节", "processing"),
    "logistics": ("🚚", "物流运输环节", "logistics"),
    "retail": ("🏪", "零售上架环节", "retail"),
    "sale": ("🛒", "销售环节", "sale"),
}

RECORD_META = {
    "seed": ("🌱", "种苗投放"),
    "feed": ("🍚", "饲料投喂"),
    "fertilize": ("🧪", "施肥记录"),
    "medicine": ("💊", "用药记录"),
    "water": ("💧", "水质/环境检测"),
    "harvest": ("🪝", "采摘/捕捞"),
    "warehouse": ("📦", "批次入库"),
    "process": ("🔪", "加工记录"),
    "package": ("🎁", "包装记录"),
    "temperature": ("🌡️", "冷链温度"),
    "track": ("📍", "运输轨迹"),
    "ship": ("🚛", "运输发车"),
    "list": ("🏷️", "零售上架"),
    "sale": ("💰", "销售成交"),
}


def gen_batch_code():
    return "TRC" + time.strftime("%Y%m%d%H%M%S") + str(random.randint(100, 999))


def gen_order_no():
    return "ORD" + time.strftime("%Y%m%d%H%M%S") + str(random.randint(1000, 9999))


def gen_tracking_no():
    return "LOG" + time.strftime("%Y%m%d%H%M") + str(random.randint(100, 999))


# ---------------------------------------------------------------------------
# 批次
# ---------------------------------------------------------------------------
def create_batch(owner, product_name, category, origin, description, quantity, unit):
    code = gen_batch_code()
    bid = db.execute(
        "INSERT INTO batches(batch_code,product_name,category,origin,description,quantity,unit,owner_id,owner_role)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (code, product_name, category, origin, description, quantity, unit, owner["id"], owner["role"]),
        fetch_id=True,
    )
    # 创建种养环节
    db.execute(
        "INSERT INTO stages(batch_id,stage_type,stage_name,operator_id) VALUES(?,?,?,?)",
        (bid, "farming", "种养建档", owner["id"]),
    )
    return get_batch_by_code(code)


def get_batch_by_code(code):
    return db.query("SELECT * FROM batches WHERE batch_code = ?", (code,), one=True)


def get_batch_by_id(bid):
    return db.query("SELECT * FROM batches WHERE id = ?", (bid,), one=True)


def list_batches(owner_id=None, limit=100):
    if owner_id:
        return db.query(
            "SELECT * FROM batches WHERE owner_id = ? ORDER BY id DESC LIMIT ?", (owner_id, limit)
        )
    return db.query("SELECT * FROM batches ORDER BY id DESC LIMIT ?", (limit,))


def count_batches():
    return db.query("SELECT COUNT(*) c FROM batches", one=True)["c"]


def get_stages(batch_id):
    return db.query("SELECT * FROM stages WHERE batch_id = ? ORDER BY id", (batch_id,))


def get_records(batch_id):
    return db.query("SELECT * FROM records WHERE batch_id = ? ORDER BY id", (batch_id,))


def get_record(rid):
    return db.query("SELECT * FROM records WHERE id = ?", (rid,), one=True)


# ---------------------------------------------------------------------------
# 记录：录入 → 哈希 → 上链 → 落库
# ---------------------------------------------------------------------------
def add_record(batch_code, record_type, record_name, content, operator):
    """录入一条溯源记录，返回 (record, error)。content 为 dict。"""
    batch = get_batch_by_code(batch_code)
    if not batch:
        return None, "批次不存在"
    if record_type not in RECORD_STAGE:
        return None, "非法记录类型"

    stage_type = RECORD_STAGE[record_type]
    # 保证环节存在
    stage = db.query(
        "SELECT * FROM stages WHERE batch_id = ? AND stage_type = ? ORDER BY id DESC LIMIT 1",
        (batch["id"], stage_type), one=True,
    )
    if not stage:
        meta = STAGE_META[stage_type]
        sid = db.execute(
            "INSERT INTO stages(batch_id,stage_type,stage_name,operator_id) VALUES(?,?,?,?)",
            (batch["id"], stage_type, meta[1], operator["id"]), fetch_id=True,
        )
    else:
        sid = stage["id"]

    # 同批次上一条记录 → prev_hash（哈希链）
    prev = db.query(
        "SELECT data_hash FROM records WHERE batch_id = ? ORDER BY id DESC LIMIT 1",
        (batch["id"],), one=True,
    )
    prev_hash = prev["data_hash"] if prev else None

    data_hash = content_hash(content)
    chain = get_chain()
    try:
        c = chain.add_record(batch_code, data_hash, stage_type, operator["username"])
        chain_status = "onchain" if c.get("ok") else "failed"
        chain_tx = c.get("tx")
        chain_block = c.get("block")
    except Exception as e:
        chain_status, chain_tx, chain_block = "failed", str(e)[:80], None

    content_json = json.dumps(content, ensure_ascii=False)
    rid = db.execute(
        "INSERT INTO records(batch_id,stage_id,record_type,record_name,content,operator_id,operator_name,"
        "data_hash,prev_hash,chain_status,chain_tx,chain_block)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (batch["id"], sid, record_type, record_name, content_json, operator["id"],
         operator["real_name"], data_hash, prev_hash, chain_status, chain_tx, chain_block),
        fetch_id=True,
    )
    # 推进批次当前环节
    db.execute("UPDATE batches SET current_stage = ? WHERE id = ?", (stage_type, batch["id"]))
    # 使溯源缓存失效
    invalidate_cache(batch_code)
    return get_record(rid), None


def _parse_content(rec):
    try:
        c = json.loads(rec["content"]) if rec["content"] else {}
        if isinstance(c, str):
            return {"text": c}
        return c
    except Exception:
        return {"text": rec["content"]}


# ---------------------------------------------------------------------------
# 校验（防篡改核心）
# ---------------------------------------------------------------------------
def verify_record(rec):
    """单条记录校验：内容重算哈希 + 链上存在性 + 哈希链链接。"""
    content = _parse_content(rec)
    recomputed = content_hash(content)
    chain = get_chain()
    issues = []
    if recomputed != rec["data_hash"]:
        issues.append(f"库中内容与登记指纹不一致（内容可能被篡改）")
    onchain = chain.verify_hash(rec["data_hash"])
    if not onchain.get("exists"):
        issues.append("指纹未在链上找到（上链存证缺失）")
    if rec["prev_hash"]:
        prev_rec = db.query(
            "SELECT data_hash FROM records WHERE batch_id = ? AND id < ? ORDER BY id DESC LIMIT 1",
            (rec["batch_id"], rec["id"]), one=True,
        )
        if prev_rec and prev_rec["data_hash"] != rec["prev_hash"]:
            issues.append("哈希链链接断裂（前序记录被改动）")
    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "recomputed": recomputed,
        "onchain": onchain,
    }


def verify_batch(batch_code):
    batch = get_batch_by_code(batch_code)
    if not batch:
        return None
    records = get_records(batch["id"])
    results = []
    for r in records:
        v = verify_record(r)
        results.append({"record": r, "verify": v})
    ok = all(v["verify"]["ok"] for v in results)
    return {"batch": batch, "results": results, "ok": ok,
            "ok_count": sum(1 for v in results if v["verify"]["ok"]),
            "bad_count": sum(1 for v in results if not v["verify"]["ok"])}


# ---------------------------------------------------------------------------
# 溯源报告（含缓存）
# ---------------------------------------------------------------------------
def _row_to_dict(row):
    """sqlite3.Row → dict，保证 JSON 缓存序列化后字段完整。"""
    return dict(row) if row is not None else None


def build_report(batch_code, fresh=False):
    """组装溯源报告。fresh=True 强制绕过缓存。"""
    cache_key = f"trace_report:{batch_code}"
    hit = False
    if not fresh:
        cached = cache.get(cache_key)
        if cached:
            hit = True
            try:
                data = json.loads(cached)
                data["cache"] = {"hit": True, "backend": cache.backend_name()}
                return data
            except Exception:
                pass

    batch = get_batch_by_code(batch_code)
    if not batch:
        return None

    records = get_records(batch["id"])
    stages = get_stages(batch["id"])

    timeline = []
    for r in records:
        content = _parse_content(r)
        v = verify_record(r)
        stage_type = RECORD_STAGE.get(r["record_type"], "farming")
        icon, name = RECORD_META.get(r["record_type"], ("📋", r["record_type"]))
        timeline.append({
            "record": _row_to_dict(r),
            "content": content,
            "stage_type": stage_type,
            "icon": icon,
            "name": name,
            "verify": v,
            "display_time": r["created_at"],
        })

    # 关联的商品（商城可售/历史售卖）
    products = [_row_to_dict(p) for p in db.query(
        "SELECT * FROM products WHERE batch_id = ? ORDER BY id DESC LIMIT 10", (batch["id"],)
    )]
    orders = [_row_to_dict(o) for o in db.query(
        "SELECT DISTINCT o.* FROM orders o JOIN order_items oi ON oi.order_id = o.id"
        " WHERE oi.batch_id = ? ORDER BY o.id DESC LIMIT 10", (batch["id"],)
    )]

    data = {
        "batch": _row_to_dict(batch),
        "stages": [_row_to_dict(s) for s in stages],
        "timeline": timeline,
        "products": products,
        "orders": orders,
        "ok": all(t["verify"]["ok"] for t in timeline),
        "verified_count": sum(1 for t in timeline if t["verify"]["ok"]),
        "chain_name": get_chain().chain_name(),
        "chain_integrity": get_chain().integrity_check(),
        "cache": {"hit": False, "backend": cache.backend_name()},
    }
    # 写入缓存（过期 TTL 由缓存服务控制）
    try:
        cache.set(cache_key, json.dumps(data, ensure_ascii=False, default=str))
    except Exception:
        pass
    return data


def invalidate_cache(batch_code):
    cache_key = f"trace_report:{batch_code}"
    # 内存/Redis 统一删除（Redis 用 del，本地缓存 pop）
    if cache.redis is not None:
        try:
            cache.redis.delete(cache_key)
        except Exception:
            pass
    cache.local._store.pop(cache_key, None)


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------
def count_records():
    return db.query("SELECT COUNT(*) c FROM records", one=True)["c"]


def count_onchain():
    return db.query("SELECT COUNT(*) c FROM records WHERE chain_status='onchain'", one=True)["c"]
