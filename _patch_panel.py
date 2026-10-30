# -*- coding: utf-8 -*-
import io
p = r"D:\pythonProject1\自然语言\实践\功能\blueprints\panel.py"
s = io.open(p, encoding="utf-8").read()

# 1) import db
old1 = """from services import trace_service as ts
from services import mall_service as ms

bp = Blueprint("panel", __name__)"""
new1 = """from services import trace_service as ts
from services import mall_service as ms
from database import db

bp = Blueprint("panel", __name__)"""
assert old1 in s, "anchor1 not found"
s = s.replace(old1, new1, 1)

# 2) add helper after _guard
helper = '''    return None


def _seller_sales(seller_id, limit=15):
    """某卖家的销售去向：买家、货物、物流商、订单状态。"""
    rows = db.query(
        "SELECT o.order_no, o.total_amount, o.status, o.created_at, "
        "ub.real_name buyer_name, ul.real_name logistics_name"
        " FROM orders o"
        " LEFT JOIN users ub ON ub.id = o.buyer_id"
        " LEFT JOIN users ul ON ul.id = o.logistics_id"
        " WHERE o.seller_id = ? ORDER BY o.id DESC LIMIT ?",
        (seller_id, limit),
    )
    out = []
    for o in rows:
        full = db.query("SELECT id FROM orders WHERE order_no=?", (o["order_no"],), one=True)
        items = db.query("SELECT product_name, quantity FROM order_items WHERE order_id=?", (full["id"],))
        d = dict(o)
        d["items"] = "、".join(f"{it['product_name']}x{it['quantity']}" for it in items)
        out.append(d)
    return out
'''
anchor2 = '    return None\n\n\n@bp.route("/panel")'
assert anchor2 in s, "anchor2 not found"
s = s.replace(anchor2, helper + "\n@bp.route(\"/panel\")", 1)

# 3) farmer
old3 = '    return render_template("panel/farmer_dashboard.html", batches=batches, stats=stats)'
new3 = ('    sales = _seller_sales(g.user["id"])\n'
        '    return render_template("panel/farmer_dashboard.html", batches=batches, stats=stats, sales=sales)')
assert old3 in s, "anchor3 not found"
s = s.replace(old3, new3, 1)

# 4) contractor
old4 = '    return render_template("panel/contractor_dashboard.html", batches=batches, available=available)'
new4 = ('    sales = _seller_sales(g.user["id"])\n'
        '    return render_template("panel/contractor_dashboard.html", batches=batches, available=available, sales=sales)')
assert old4 in s, "anchor4 not found"
s = s.replace(old4, new4, 1)

io.open(p, "w", encoding="utf-8").write(s)
print("panel.py patched OK")
