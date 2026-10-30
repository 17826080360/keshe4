# -*- coding: utf-8 -*-
"""
商城服务：商品、购物车、订单、物流运单、资金托管结算。
买卖安心 = 资金托管 + 每笔交易与物流都上链存证，买家随时可溯。
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import db
from services import user_service
from services import trace_service as ts

PLATFORM_FEE_RATE = 0.02  # 平台手续费 2%


# ---------------------------------------------------------------------------
# 商品
# ---------------------------------------------------------------------------
def create_product(seller, title, category, description, price, stock, unit, image,
                   product_type="goods", batch_code=None):
    bid = None
    if batch_code:
        b = ts.get_batch_by_code(batch_code)
        if not b:
            return None, "溯源批次不存在"
        bid = b["id"]
    pid = db.execute(
        "INSERT INTO products(seller_id,seller_role,title,category,description,price,stock,unit,image,"
        "product_type,batch_id,status)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,'on_sale')",
        (seller["id"], seller["role"], title, category, description, price, stock, unit, image,
         product_type, bid),
        fetch_id=True,
    )
    # 上架即上链（零售环节记录）
    if bid:
        ts.add_record(b["batch_code"], "list", "商品上架", {
            "product_id": pid, "title": title, "price": price,
            "seller": seller["real_name"], "seller_role": seller["role"],
        }, seller)
    return get_product(pid), None


def get_product(pid):
    p = db.query("SELECT * FROM products WHERE id = ?", (pid,), one=True)
    if not p:
        return None
    batch = None
    if p["batch_id"]:
        batch = ts.get_batch_by_id(p["batch_id"])
    return dict(p) | {"batch": batch}


def list_products(category=None, seller_role=None, keyword=None, product_type=None, status="on_sale"):
    sql = "SELECT p.*, u.real_name seller_name, u.company seller_company FROM products p" \
          " JOIN users u ON u.id = p.seller_id WHERE p.status = ?"
    args = [status]
    if category and category != "全部":
        sql += " AND p.category = ?"
        args.append(category)
    if seller_role and seller_role != "全部":
        sql += " AND p.seller_role = ?"
        args.append(seller_role)
    if product_type and product_type != "全部":
        sql += " AND p.product_type = ?"
        args.append(product_type)
    if keyword:
        sql += " AND (p.title LIKE ? OR p.description LIKE ?)"
        args += [f"%{keyword}%", f"%{keyword}%"]
    sql += " ORDER BY p.id DESC LIMIT 60"
    return db.query(sql, args)


def set_product_status(pid, status):
    db.execute("UPDATE products SET status = ? WHERE id = ?", (status, pid))


def categories():
    return [r["category"] for r in db.query(
        "SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != ''")]


def count_products():
    return db.query("SELECT COUNT(*) c FROM products", one=True)["c"]


def count_on_sale():
    return db.query("SELECT COUNT(*) c FROM products WHERE status='on_sale'", one=True)["c"]


# ---------------------------------------------------------------------------
# 购物车
# ---------------------------------------------------------------------------
def add_cart(user_id, product_id, qty):
    p = get_product(product_id)
    if not p or p["status"] != "on_sale":
        return False, "商品不存在或已下架"
    if p["product_type"] == "goods" and p["stock"] < qty:
        return False, "库存不足"
    exist = db.query(
        "SELECT * FROM cart_items WHERE user_id = ? AND product_id = ?", (user_id, product_id), one=True
    )
    if exist:
        db.execute("UPDATE cart_items SET quantity = quantity + ? WHERE id = ?", (qty, exist["id"]))
    else:
        db.execute("INSERT INTO cart_items(user_id,product_id,quantity) VALUES(?,?,?)",
                   (user_id, product_id, qty))
    return True, None


def get_cart(user_id):
    rows = db.query(
        "SELECT c.*, p.title, p.price, p.image, p.stock, p.product_type, p.batch_id, p.seller_id,"
        " u.real_name seller_name FROM cart_items c"
        " JOIN products p ON p.id = c.product_id JOIN users u ON u.id = p.seller_id"
        " WHERE c.user_id = ? ORDER BY c.id", (user_id,),
    )
    total = sum(r["price"] * r["quantity"] for r in rows)
    return rows, round(total, 2)


def update_cart_item(item_id, qty):
    if qty <= 0:
        db.execute("DELETE FROM cart_items WHERE id = ?", (item_id,))
    else:
        db.execute("UPDATE cart_items SET quantity = ? WHERE id = ?", (qty, item_id))


def clear_cart(user_id, product_ids=None):
    if product_ids:
        marks = ",".join("?" * len(product_ids))
        db.execute(f"DELETE FROM cart_items WHERE user_id = ? AND product_id IN ({marks})",
                   [user_id] + product_ids)
    else:
        db.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))


# ---------------------------------------------------------------------------
# 订单
# ---------------------------------------------------------------------------
def create_order(buyer, items, address, remark=""):
    """items: [(product_id, qty)]。校验库存并扣减（预占）。"""
    if not items:
        return None, "购物车为空"
    total = 0.0
    detail = []
    for pid, qty in items:
        p = get_product(pid)
        if not p or p["status"] != "on_sale":
            return None, "部分商品已下架"
        if p["seller_id"] == buyer["id"]:
            return None, "不能购买自己发布的商品"
        if p["product_type"] == "goods" and p["stock"] < qty:
            return None, f"「{p['title']}」库存不足"
        amount = round(p["price"] * qty, 2)
        total += amount
        detail.append((p, qty, amount))
    seller_ids = {p["seller_id"] for p, _, _ in detail}
    if len(seller_ids) > 1:
        return None, "请分单结算：同一订单仅支持同一卖家（当前为演示简化）"
    seller_id = list(seller_ids)[0]

    for p, qty, _ in detail:
        db.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (qty, p["id"]))

    order_no = ts.gen_order_no()
    oid = db.execute(
        "INSERT INTO orders(order_no,buyer_id,seller_id,order_type,total_amount,status,shipping_address,remark)"
        " VALUES(?,?,?,?,?,'pending_payment',?,?)",
        (order_no, buyer["id"], seller_id, detail[0][0]["product_type"], round(total, 2), address, remark),
        fetch_id=True,
    )
    for p, qty, amount in detail:
        db.execute(
            "INSERT INTO order_items(order_id,product_id,product_name,batch_id,trace_code,price,quantity,amount)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (oid, p["id"], p["title"], p["batch_id"],
             p["batch"]["batch_code"] if p["batch"] else None, p["price"], qty, amount),
        )
    clear_cart(buyer["id"], [p["id"] for p, _, _ in detail])
    return get_order(oid), None


def get_order(oid):
    o = db.query("SELECT * FROM orders WHERE id = ?", (oid,), one=True)
    if not o:
        return None
    items = db.query("SELECT * FROM order_items WHERE order_id = ?", (oid,))
    buyer = user_service.find_user_by_id(o["buyer_id"])
    seller = user_service.find_user_by_id(o["seller_id"])
    logistics = user_service.find_user_by_id(o["logistics_id"]) if o["logistics_id"] else None
    shipment = db.query("SELECT * FROM shipments WHERE order_id = ?", (oid,), one=True)
    return dict(o) | {
        "items": items, "buyer": buyer, "seller": seller,
        "logistics": logistics, "shipment": shipment,
    }


def list_orders(user_id, side="buy", status=None, limit=100):
    col = "buyer_id" if side == "buy" else "seller_id"
    sql = f"SELECT o.*, u.real_name other_name FROM orders o JOIN users u ON u.id = o.{col} WHERE o.{col} = ?"
    args = [user_id]
    if status and status != "全部":
        sql += " AND o.status = ?"
        args.append(status)
    sql += " ORDER BY o.id DESC LIMIT ?"
    args.append(limit)
    return db.query(sql, args)


def _settle_escrow(order):
    """订单完成：托管资金结算给卖家，平台扣手续费。"""
    fee = round(order["total_amount"] * PLATFORM_FEE_RATE, 2)
    income = round(order["total_amount"] - fee, 2)
    # 平台(admin) → 卖家
    admin = user_service.find_user("admin")
    ok, err = user_service.transfer(admin["id"], order["seller_id"], income, "income",
                                    order["order_no"], f"订单{order['order_no']}销售货款（已扣平台费{fee}元）")
    if not ok:
        return False, err
    db.execute("UPDATE orders SET platform_fee = ?, seller_income = ? WHERE id = ?",
               (fee, income, order["id"]))
    return True, None


def pay_order(order_id, buyer):
    o = get_order(order_id)
    if not o or o["buyer_id"] != buyer["id"]:
        return False, "订单不存在"
    if o["status"] != "pending_payment":
        return False, "订单状态不允许支付"
    # 买家 → 平台托管
    admin = user_service.find_user("admin")
    ok, err = user_service.transfer(buyer["id"], admin["id"], o["total_amount"], "pay",
                                    o["order_no"], f"订单{o['order_no']}货款托管")
    if not ok:
        return False, err
    db.execute("UPDATE orders SET status='paid', paid_at=datetime('now','localtime') WHERE id = ?", (order_id,))
    return True, None


def cancel_order(order_id, user):
    o = get_order(order_id)
    if not o or (o["buyer_id"] != user["id"] and o["seller_id"] != user["id"]):
        return False, "无权操作"
    if o["status"] not in ("pending_payment", "paid"):
        return False, "当前状态不可取消"
    # 归还库存
    if o["order_type"] == "goods":
        for it in o["items"]:
            db.execute("UPDATE products SET stock = stock + ? WHERE id = ?", (it["quantity"], it["product_id"]))
    db.execute("UPDATE orders SET status='cancelled' WHERE id = ?", (order_id,))
    return True, None


def ship_order(order_id, seller, logistics_id, tracking_no):
    """卖家发货：选择物流公司，生成运单并上链运输发车记录。"""
    o = get_order(order_id)
    if not o or o["seller_id"] != seller["id"]:
        return False, "无权操作"
    if o["status"] != "paid":
        return False, "仅已付款订单可发货"
    lg = user_service.find_user_by_id(logistics_id)
    if not lg or lg["role"] != "logistics":
        return False, "请选择有效的物流公司"
    sid = db.execute(
        "INSERT INTO shipments(order_id,logistics_id,tracking_no,cold_chain) VALUES(?,?,?,1)",
        (order_id, logistics_id, tracking_no), fetch_id=True,
    )
    db.execute("UPDATE orders SET status='shipped', logistics_id=?, tracking_no=?, shipped_at=datetime('now','localtime') WHERE id = ?",
               (logistics_id, tracking_no, order_id))
    # 物流环节上链
    for it in o["items"]:
        if it["trace_code"]:
            ts.add_record(it["trace_code"], "ship", "运输发车", {
                "order_no": o["order_no"], "tracking_no": tracking_no,
                "logistics": lg["real_name"], "from": seller["real_name"],
                "to_address": o["shipping_address"], "cold_chain": True,
            }, seller)
    return True, None


def list_logistics_companies():
    return db.query("SELECT * FROM users WHERE role='logistics' AND status='active'")


def list_shipments(logistics_id=None, status=None, limit=100):
    sql = ("SELECT s.*, o.order_no, o.buyer_id, u.real_name buyer_name, o.shipping_address "
           "FROM shipments s JOIN orders o ON o.id = s.order_id JOIN users u ON u.id = o.buyer_id")
    args = []
    if logistics_id:
        sql += " WHERE s.logistics_id = ?"
        args.append(logistics_id)
        if status and status != "全部":
            sql += " AND s.status = ?"
            args.append(status)
    sql += " ORDER BY s.id DESC LIMIT ?"
    args.append(limit)
    return db.query(sql, args)


def get_shipment(sid):
    s = db.query(
        "SELECT s.*, o.order_no, o.shipping_address, o.buyer_id, o.seller_id,"
        " u.real_name buyer_name FROM shipments s"
        " JOIN orders o ON o.id = s.order_id JOIN users u ON u.id = o.buyer_id"
        " WHERE s.id = ?", (sid,), one=True)
    if not s:
        return None
    temps = db.query("SELECT * FROM temperature_logs WHERE shipment_id = ? ORDER BY id DESC LIMIT 50", (sid,))
    tracks = db.query("SELECT * FROM track_points WHERE shipment_id = ? ORDER BY id", (sid,))
    return dict(s) | {"temps": temps, "tracks": tracks}


def shipment_pickup(sid, logistics_id):
    s = get_shipment(sid)
    if not s or s["logistics_id"] != logistics_id:
        return False, "无权操作"
    db.execute("UPDATE shipments SET status='picked_up', picked_at=datetime('now','localtime') WHERE id = ?", (sid,))
    return True, None


def shipment_add_track(sid, logistics_id, location, description):
    s = get_shipment(sid)
    if not s or s["logistics_id"] != logistics_id:
        return False, "无权操作"
    db.execute(
        "INSERT INTO track_points(shipment_id,location,description) VALUES(?,?,?)",
        (sid, location, description))
    _chain_logistics_record(s, "track", "运输轨迹", {
        "tracking_no": s["tracking_no"], "location": location, "description": description,
    }, logistics_id)
    return True, None


def shipment_report_temp(sid, logistics_id, temperature, location):
    s = get_shipment(sid)
    if not s or s["logistics_id"] != logistics_id:
        return False, "无权操作"
    content = {"tracking_no": s["tracking_no"], "temperature": temperature,
               "location": location, "cold_chain": True}
    data_hash = ts.content_hash(content)
    chain = get_chain_safe()
    try:
        c = chain.add_record("LOG:" + s["tracking_no"], data_hash, "logistics", "logistics")
        cstatus, ctx = ("onchain", c.get("tx")) if c.get("ok") else ("failed", None)
    except Exception:
        cstatus, ctx = "failed", None
    db.execute(
        "INSERT INTO temperature_logs(shipment_id,temperature,location,data_hash,chain_status,chain_tx)"
        " VALUES(?,?,?,?,?,?)",
        (sid, temperature, location, data_hash, cstatus, ctx))
    _chain_logistics_record(s, "temperature", "冷链温度", content, logistics_id)
    return True, None


def _chain_logistics_record(shipment, record_type, name, content, logistics_id):
    """把物流事件写入关联批次的溯源链。"""
    lg = user_service.find_user_by_id(logistics_id)
    o = get_order(shipment["order_id"])
    if not o:
        return
    for it in o["items"]:
        if it["trace_code"]:
            ts.add_record(it["trace_code"], record_type, name, content, lg)


def shipment_deliver(sid, logistics_id):
    s = get_shipment(sid)
    if not s or s["logistics_id"] != logistics_id:
        return False, "无权操作"
    db.execute("UPDATE shipments SET status='delivered', delivered_at=datetime('now','localtime') WHERE id = ?", (sid,))
    return True, None


def confirm_receipt(order_id, buyer):
    """买家确认收货：完成订单、结算托管资金、销售上链、零售商入库。"""
    o = get_order(order_id)
    if not o or o["buyer_id"] != buyer["id"]:
        return False, "无权操作"
    if o["status"] != "shipped":
        return False, "仅运输中订单可确认收货"
    # 结算
    ok, err = _settle_escrow(o)
    if not ok:
        return False, err
    db.execute("UPDATE orders SET status='completed', completed_at=datetime('now','localtime') WHERE id = ?",
               (order_id,))
    # 销量
    for it in o["items"]:
        if it["product_id"]:
            db.execute("UPDATE products SET sales_count = sales_count + ? WHERE id = ?",
                       (it["quantity"], it["product_id"]))
        # 零售商进货 → 入库
        if buyer["role"] == "retailer" and it["batch_id"]:
            inv = db.query(
                "SELECT * FROM inventory WHERE retailer_id = ? AND batch_id = ?",
                (buyer["id"], it["batch_id"]), one=True)
            if inv:
                db.execute("UPDATE inventory SET quantity = quantity + ?, updated_at=datetime('now','localtime') WHERE id = ?",
                           (it["quantity"], inv["id"]))
            else:
                db.execute(
                    "INSERT INTO inventory(retailer_id,batch_id,product_id,quantity,unit) VALUES(?,?,?,?,?)",
                    (buyer["id"], it["batch_id"], it["product_id"], it["quantity"], o["items"][0]["product_id"] and "件" or "kg"))
        # 销售上链（销售环节）
        if it["trace_code"]:
            ts.add_record(it["trace_code"], "sale", "销售成交", {
                "order_no": o["order_no"], "buyer": buyer["real_name"],
                "seller": o["seller"]["real_name"], "product": it["product_name"],
                "quantity": it["quantity"], "amount": it["amount"],
            }, buyer)
    return True, None


def complete_service(order_id, seller):
    """物流服务订单：卖家确认服务完成。"""
    o = get_order(order_id)
    if not o or o["seller_id"] != seller["id"]:
        return False, "无权操作"
    if o["status"] != "paid":
        return False, "仅已付款服务订单可完成"
    ok, err = _settle_escrow(o)
    if not ok:
        return False, err
    db.execute("UPDATE orders SET status='completed', completed_at=datetime('now','localtime') WHERE id = ?",
               (order_id,))
    for it in o["items"]:
        if it["product_id"]:
            db.execute("UPDATE products SET sales_count = sales_count + ? WHERE id = ?",
                       (it["quantity"], it["product_id"]))
    return True, None


def list_buyer_orders(uid):
    rows = db.query(
        "SELECT o.id, o.order_no, o.status,"
        " (SELECT GROUP_CONCAT(product_name || ' x' || quantity) FROM order_items oi WHERE oi.order_id=o.id) items"
        " FROM orders o WHERE o.buyer_id=? ORDER BY o.id DESC", (uid,))
    return [dict(r) for r in rows]


def list_conversations(uid):
    rows = db.query(
        "SELECT o.id, o.order_no, o.buyer_id, o.seller_id, o.created_at,"
        " (SELECT m.content FROM order_messages m WHERE m.order_id=o.id ORDER BY m.id DESC LIMIT 1) last_msg,"
        " (SELECT m.created_at FROM order_messages m WHERE m.order_id=o.id ORDER BY m.id DESC LIMIT 1) last_at,"
        " (SELECT u.real_name FROM users u WHERE u.id = CASE WHEN o.buyer_id=? THEN o.seller_id ELSE o.buyer_id END) peer_name,"
        " (SELECT u.role FROM users u WHERE u.id = CASE WHEN o.buyer_id=? THEN o.seller_id ELSE o.buyer_id END) peer_role"
        " FROM orders o WHERE o.buyer_id=? OR o.seller_id=?"
        " ORDER BY last_at DESC, o.id DESC",
        (uid, uid, uid, uid))
    out = []
    for r in rows:
        r = dict(r)
        r["items"] = db.query(
            "SELECT product_name, quantity FROM order_items WHERE order_id=?", (r["id"],))
        out.append(r)
    return out


def list_messages(order_id):
    return db.query(
        "SELECT m.*, u.real_name sender_name, u.role sender_role"
        " FROM order_messages m JOIN users u ON u.id = m.sender_id"
        " WHERE m.order_id = ? ORDER BY m.id", (order_id,))


def add_message(order_id, sender_id, content):
    content = (content or "").strip()
    if not content:
        return False
    db.execute(
        "INSERT INTO order_messages(order_id,sender_id,content) VALUES(?,?,?)",
        (order_id, sender_id, content))
    return True


def get_chain_safe():
    from blockchain.chain_backend import get_chain
    return get_chain()


# ---------------------------------------------------------------------------
# 零售商：库存与转售
# ---------------------------------------------------------------------------
def list_inventory(retailer_id):
    return db.query(
        "SELECT i.*, b.batch_code, b.product_name, b.unit b_unit, b.origin,"
        " (SELECT MIN(price) FROM products WHERE batch_id = i.batch_id) ref_price"
        " FROM inventory i JOIN batches b ON b.id = i.batch_id"
        " WHERE i.retailer_id = ? AND i.quantity > 0 ORDER BY i.id DESC", (retailer_id,))


def retailer_resale(retailer, inv_id, title, price, qty, description, image):
    inv = db.query("SELECT * FROM inventory WHERE id = ? AND retailer_id = ?",
                   (inv_id, retailer["id"]), one=True)
    if not inv or inv["quantity"] < qty:
        return None, "库存不足"
    b = ts.get_batch_by_id(inv["batch_id"])
    db.execute("UPDATE inventory SET quantity = quantity - ? WHERE id = ?", (qty, inv_id))
    pid = db.execute(
        "INSERT INTO products(seller_id,seller_role,title,category,description,price,stock,unit,image,"
        "product_type,batch_id,source_product_id,status)"
        " VALUES(?,?,?,?,?,?,?,?,?, 'goods',?,?,'on_sale')",
        (retailer["id"], "retailer", title, b["category"], description, price, qty,
         b["unit"], image, b["id"], inv["product_id"]), fetch_id=True)
    # 上架上链
    ts.add_record(b["batch_code"], "list", "零售上架", {
        "product_id": pid, "title": title, "price": price,
        "seller": retailer["real_name"], "seller_role": "retailer",
        "note": "零售商转售",
    }, retailer)
    return get_product(pid), None


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------
def count_orders():
    return db.query("SELECT COUNT(*) c FROM orders", one=True)["c"]


def sum_gmv():
    r = db.query("SELECT IFNULL(SUM(total_amount),0) s FROM orders WHERE status='completed'", one=True)
    return round(r["s"], 2)


def count_shipments():
    return db.query("SELECT COUNT(*) c FROM shipments", one=True)["c"]
