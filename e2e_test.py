# -*- coding: utf-8 -*-
"""端到端全流程测试：登录→商城→下单→支付→发货→物流→收货→溯源→篡改演示。"""
import json
import re
import requests

BASE = "http://127.0.0.1:5000"


def client():
    s = requests.Session()
    return s


def login(s, username, password="123456"):
    r = s.post(BASE + "/login", data={"username": username, "password": password}, allow_redirects=True)
    return "欢迎" in r.text


def get_codes():
    from database import db
    return [r["batch_code"] for r in db.query("SELECT batch_code FROM batches ORDER BY id")]


def test():
    ok_all = True

    def check(name, cond, extra=""):
        nonlocal ok_all
        print(("✅ " if cond else "❌ ") + name + (("  " + str(extra)) if extra and not cond else ""))
        if not cond:
            ok_all = False

    # ---------- 1. 首页与公开页 ----------
    r = requests.get(BASE + "/")
    check("首页 200", r.status_code == 200 and "安心溯源商城" in r.text)
    r = requests.get(BASE + "/mall")
    check("商城列表 200", r.status_code == 200 and "安心商城" in r.text)
    codes = get_codes()
    # 未登录访问溯源 → 必须被拦截跳转登录页
    r = requests.get(BASE + f"/trace/{codes[0]}", allow_redirects=False)
    check("未登录溯源被拦截(302→登录)", r.status_code in (301, 302) and "/login" in r.headers.get("Location", ""))
    r = requests.get(BASE + f"/trace/{codes[0]}")
    check("未登录溯源跳转登录页", "登录" in r.text and "溯源查询需要登录" in r.text)

    # ---------- 2. 消费者登录与购物 ----------
    s = client()
    check("消费者登录", login(s, "consumer1"))
    # 登录后溯源可用 + 缓存命中
    r = s.get(BASE + f"/trace/{codes[0]}")
    check("登录后溯源报告 200", r.status_code == 200 and "链上验证通过" in r.text)
    r2 = s.get(BASE + f"/trace/{codes[0]}")
    check("溯源缓存命中", "缓存命中" in r2.text)
    r = s.get(BASE + "/cart")
    check("购物车页", r.status_code == 200)

    # 找一个可购买商品（非自己发布、有库存）
    prods = requests.get(BASE + "/mall").text
    import re as _re
    # 通过首页商品卡片取第一个商品 id
    from database import db as dbb
    p = dbb.query("SELECT p.* FROM products p WHERE p.status='on_sale' AND p.stock>0 AND p.seller_id != (SELECT id FROM users WHERE username='consumer1') ORDER BY p.id LIMIT 1", one=True)
    check("存在可购商品", p is not None)
    pid = p["id"]

    r = s.post(BASE + "/cart/add", data={"product_id": pid, "quantity": 2}, allow_redirects=True)
    check("加入购物车", "已加入购物车" in r.text)

    # 直接下单购买
    r = s.post(BASE + "/checkout", data={"address": "武汉市光谷大道 88 号", "buy_now": pid, "quantity": 1}, allow_redirects=True)
    m = re.search(r"/order/(\d+)", r.url)
    check("下单成功", m is not None, r.url)
    oid = int(m.group(1))
    r = s.get(BASE + f"/order/{oid}")
    check("订单详情 200", r.status_code == 200 and "订单" in r.text)

    # 支付
    r = s.post(BASE + f"/order/{oid}/pay", allow_redirects=True)
    check("支付托管成功", "支付成功" in r.text)

    # ---------- 3. 卖家发货 + 物流 ----------
    order = dbb.query("SELECT * FROM orders WHERE id=?", (oid,), one=True)
    seller = dbb.query("SELECT username FROM users WHERE id=?", (order["seller_id"],), one=True)["username"]
    s2 = client()
    check("卖家登录", login(s2, seller))
    lg = dbb.query("SELECT id FROM users WHERE role='logistics' LIMIT 1", one=True)["id"]
    r = s2.post(BASE + f"/order/{oid}/ship", data={"logistics_id": lg, "tracking_no": ""}, allow_redirects=True)
    check("卖家发货", "发货成功" in r.text)

    ship = dbb.query("SELECT * FROM shipments WHERE order_id=?", (oid,), one=True)
    check("运单已创建", ship is not None)
    s3 = client()
    check("物流登录", login(s3, "logistics1"))
    r = s3.post(BASE + f"/logistics/shipment/{ship['id']}/pickup", allow_redirects=True)
    check("物流揽收", "已揽收" in r.text)
    r = s3.post(BASE + f"/logistics/shipment/{ship['id']}/track", data={"location": "武汉·配送中心", "description": "中转"}, allow_redirects=True)
    check("轨迹上报", "轨迹已上报" in r.text)
    r = s3.post(BASE + f"/logistics/shipment/{ship['id']}/temp", data={"temperature": -18.0, "location": "冷链车"}, allow_redirects=True)
    check("温度上报", "温度已上报" in r.text)
    r = s3.post(BASE + f"/logistics/shipment/{ship['id']}/deliver", allow_redirects=True)
    check("确认送达", "已送达" in r.text)

    # ---------- 4. 买家确认收货 ----------
    r = s.post(BASE + f"/order/{oid}/confirm", allow_redirects=True)
    check("确认收货+销售上链", "确认收货成功" in r.text)
    r = s.get(BASE + "/orders?side=buy")
    check("我的订单列表", "已完成" in r.text)

    # ---------- 5. 溯源报告包含销售记录 ----------
    item = dbb.query("SELECT trace_code FROM order_items WHERE order_id=?", (oid,), one=True)
    if item and item["trace_code"]:
        r = s.get(BASE + f"/trace/{item['trace_code']}")
        check("溯源报告含销售环节", "销售成交" in r.text and "链上验证通过" in r.text)

    # ---------- 6. 篡改演示 ----------
    sa = client()
    check("管理员登录", login(sa, "admin"))
    rec = dbb.query("SELECT * FROM records ORDER BY id DESC LIMIT 1", one=True)
    content = json.loads(rec["content"])
    field = next(iter(content.keys()))
    r = sa.post(BASE + "/admin/tamper", data={"record_id": rec["id"], "field": field, "new_value": "篡改测试999"}, allow_redirects=True)
    check("执行篡改", "已模拟篡改" in r.text)
    code = dbb.query("SELECT batch_code FROM batches WHERE id=?", (rec["batch_id"],), one=True)["batch_code"]
    r = sa.get(BASE + f"/trace/{code}")
    check("溯源报告拒绝篡改", "发现篡改" in r.text and "校验失败" in r.text)
    r = sa.post(BASE + f"/admin/tamper/{rec['id']}/restore", allow_redirects=True)
    check("恢复原文", "已恢复原文" in r.text)
    r = sa.get(BASE + f"/trace/{code}")
    check("恢复后校验通过", "链上验证通过" in r.text)

    # ---------- 7. 二维码（需登录） ----------
    r = requests.get(BASE + f"/qrcode/{codes[0]}", allow_redirects=False)
    check("未登录二维码被拦截", r.status_code in (301, 302) and "/login" in r.headers.get("Location", ""))
    r = sa.get(BASE + f"/qrcode/{codes[0]}")
    check("登录后二维码 SVG 生成", r.status_code == 200 and "svg" in r.text[:500].lower())

    # ---------- 8. 钱包流水 ----------
    r = s.get(BASE + "/wallet")
    check("钱包页面", "资金流水" in r.text)

    print("\n========== 结果：" + ("全部通过 ✅" if ok_all else "存在失败 ❌") + " ==========")
    return ok_all


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    test()
