# -*- coding: utf-8 -*-
"""页面全覆盖渲染检查：每个角色登录后访问其全部页面，确保无 500。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests

BASE = "http://127.0.0.1:5000"
fails = []

def sweep(username, pages, login_first=True):
    s = requests.Session()
    if login_first:
        r = s.post(BASE + "/login", data={"username": username, "password": "123456"}, allow_redirects=True)
        assert "欢迎" in r.text, f"{username} 登录失败"
    for path in pages:
        r = s.get(BASE + path)
        if r.status_code != 200:
            fails.append((username, path, r.status_code))

# 公开页（溯源已改为需登录，不再列入公开页）
sweep("admin", ["/", "/mall", "/login", "/register"], login_first=False)
# 未登录访问溯源应被重定向到登录页
r = requests.get(BASE + "/trace", allow_redirects=False)
if r.status_code not in (301, 302) or "/login" not in r.headers.get("Location", ""):
    fails.append(("anonymous", "/trace", r.status_code))

# 消费者
sweep("consumer1", [
    "/wallet", "/cart", "/checkout", "/orders", "/orders?side=sell", "/orders?side=buy&status=completed",
    "/mall", "/trace",
])
# 农户
sweep("farmer1", ["/panel", "/farmer", "/batches", "/products"])
# 加工商
sweep("contractor1", ["/panel", "/contractor", "/batches", "/products"])
# 物流
sweep("logistics1", ["/panel", "/logistics/shipments", "/logistics/shipments?status=delivered", "/products"])
# 零售商
sweep("retailer1", ["/panel", "/retailer/inventory", "/products", "/orders?side=buy", "/orders?side=sell"])
# 管理员
sweep("admin", ["/panel", "/admin", "/admin/users", "/admin/products", "/admin/chain", "/admin/tamper"])

# 动态详情页：所有订单详情、运单详情（物流角色）、批次详情、商品详情、溯源报告、二维码
s = requests.Session()
s.post(BASE + "/login", data={"username": "admin", "password": "123456"})
from database import db
for o in db.query("SELECT id FROM orders"):
    r = s.get(BASE + f"/order/{o['id']}")
    if r.status_code != 200:
        fails.append(("order", o["id"], r.status_code))
sl = requests.Session()
sl.post(BASE + "/login", data={"username": "logistics1", "password": "123456"})
for sh in db.query("SELECT id FROM shipments"):
    r = sl.get(BASE + f"/logistics/shipment/{sh['id']}")
    if r.status_code != 200:
        fails.append(("shipment", sh["id"], r.status_code))
for b in db.query("SELECT id, batch_code FROM batches"):
    r = s.get(BASE + f"/batches/{b['id']}")
    if r.status_code != 200:
        fails.append(("batch", b["id"], r.status_code))
    r = s.get(BASE + f"/trace/{b['batch_code']}")
    if r.status_code != 200:
        fails.append(("trace", b["batch_code"], r.status_code))
for p in db.query("SELECT id FROM products"):
    r = s.get(BASE + f"/mall/{p['id']}")
    if r.status_code != 200:
        fails.append(("product", p["id"], r.status_code))
for c in db.query("SELECT batch_code FROM batches"):
    r = s.get(BASE + f"/qrcode/{c['batch_code']}")
    if r.status_code != 200:
        fails.append(("qrcode", c["batch_code"], r.status_code))

print(f"页面检查完成：{'全部通过 ✅' if not fails else '失败 ' + str(len(fails))}")
for f in fails:
    print("  ❌", f)
