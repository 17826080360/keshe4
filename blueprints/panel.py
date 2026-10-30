# -*- coding: utf-8 -*-
"""角色工作台路由：农户/加工商/卖家商品管理、批次与记录录入。"""
import json

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort

from services import trace_service as ts
from services import mall_service as ms
from database import db

bp = Blueprint("panel", __name__)

# 各角色可录入的记录类型（表单配置）
RECORD_FORMS = {
    "farmer": [
        ("seed", "种苗投放", ["品种", "数量", "来源", "备注"]),
        ("feed", "饲料投喂", ["饲料名称", "用量", "投喂时间", "备注"]),
        ("fertilize", "施肥记录", ["肥料名称", "用量", "施肥区域", "备注"]),
        ("medicine", "用药记录", ["药品名称", "用量", "休药期(天)", "备注"]),
        ("water", "水质/环境检测", ["检测项目", "检测值", "标准范围", "备注"]),
        ("harvest", "采摘/捕捞", ["数量", "批次说明", "备注"]),
    ],
    "contractor": [
        ("warehouse", "批次入库", ["入库数量", "冷库温度", "供应商", "备注"]),
        ("process", "加工记录", ["加工工序", "加工方式", "操作人", "备注"]),
        ("package", "包装记录", ["包装方式", "包装规格", "生产日期", "备注"]),
    ],
}


def _guard(role):
    if not g.user:
        flash("请先登录", "error")
        return redirect(url_for("auth.login"))
    if g.user["role"] != role and g.user["role"] != "admin":
        abort(403)
    return None


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

@bp.route("/panel")
def home():
    if not g.user:
        return redirect(url_for("auth.login"))
    role = g.user["role"]
    if role == "farmer":
        return redirect(url_for("panel.farmer_dashboard"))
    if role == "contractor":
        return redirect(url_for("panel.contractor_dashboard"))
    if role == "logistics":
        return redirect(url_for("mall.logistics_shipments"))
    if role == "retailer":
        return redirect(url_for("mall.retailer_inventory"))
    if role == "admin":
        return redirect(url_for("admin.dashboard"))
    return redirect(url_for("mall.orders"))


# ---------------------------------------------------------------------------
# 批次管理（农户/加工商共用）
# ---------------------------------------------------------------------------
@bp.route("/batches")
def batches():
    if not g.user:
        return redirect(url_for("auth.login"))
    rows = ts.list_batches(g.user["id"])
    return render_template("panel/batches.html", rows=rows)


@bp.route("/batches/create", methods=["POST"])
def batch_create():
    if not g.user or g.user["role"] not in ("farmer", "contractor", "admin"):
        abort(403)
    product_name = request.form.get("product_name", "").strip()
    if not product_name:
        flash("产品名称不能为空", "error")
        return redirect(url_for("panel.batches"))
    b = ts.create_batch(
        g.user, product_name,
        request.form.get("category", "水产").strip(),
        request.form.get("origin", "").strip(),
        request.form.get("description", "").strip(),
        float(request.form.get("quantity", 0) or 0),
        request.form.get("unit", "kg").strip(),
    )
    flash(f"批次 {b['batch_code']} 创建成功，溯源码已生成", "success")
    return redirect(url_for("panel.batch_detail", bid=b["id"]))


@bp.route("/batches/<int:bid>")
def batch_detail(bid):
    if not g.user:
        return redirect(url_for("auth.login"))
    b = ts.get_batch_by_id(bid)
    # 访问控制：本人 / 管理员 / 加工商可入库（种养中的批次）
    allowed = (b and (b["owner_id"] == g.user["id"] or g.user["role"] == "admin"
                      or (g.user["role"] == "contractor" and b["current_stage"] == "farming")))
    if not allowed:
        abort(404)
    records = ts.get_records(bid)
    stages = ts.get_stages(bid)
    forms = RECORD_FORMS.get(g.user["role"], [])
    if g.user["role"] == "admin":
        forms = RECORD_FORMS.get(b["owner_role"], [])
    if g.user["role"] == "contractor" and b["owner_id"] != g.user["id"]:
        forms = RECORD_FORMS["contractor"]
    # 校验当前批次
    v = ts.verify_batch(b["batch_code"])
    products = ms.list_products(status="on_sale")
    my_products = [p for p in products if p["batch_id"] == bid]
    return render_template("panel/batch_detail.html", b=b, records=records, stages=stages,
                           forms=forms, verify=v, my_products=my_products)


@bp.route("/batches/<int:bid>/record", methods=["POST"])
def batch_record(bid):
    if not g.user:
        return redirect(url_for("auth.login"))
    b = ts.get_batch_by_id(bid)
    if not b:
        abort(404)
    allowed = (b["owner_id"] == g.user["id"] or g.user["role"] == "admin"
               or (g.user["role"] == "contractor" and b["current_stage"] == "farming"))
    if not allowed:
        abort(403)
    record_type = request.form.get("record_type", "")
    record_name = request.form.get("record_name", "").strip() or record_type
    # 从表单构造结构化内容
    content = {}
    for key, val in request.form.items():
        if key.startswith("f_"):
            content[key[2:]] = val.strip()
    if record_type == "harvest" and "数量" not in content and "quantity" not in content:
        content["数量"] = request.form.get("quantity", "")
    rec, err = ts.add_record(b["batch_code"], record_type, record_name, content, g.user)
    if err:
        flash(err, "error")
    else:
        status = "已上链存证" if rec["chain_status"] == "onchain" else f"上链失败：{rec['chain_tx']}"
        flash(f"记录「{record_name}」已写入，哈希 {rec['data_hash'][:18]}…，{status}", "success")
    return redirect(url_for("panel.batch_detail", bid=bid))


# ---------------------------------------------------------------------------
# 农户工作台
# ---------------------------------------------------------------------------
@bp.route("/farmer")
def farmer_dashboard():
    r = _guard("farmer")
    if r:
        return r
    batches = ts.list_batches(g.user["id"])
    stats = {
        "batches": len(batches),
        "records": sum(len(ts.get_records(b["id"])) for b in batches),
        "products": ms.count_products(),
    }
    sales = _seller_sales(g.user["id"])
    retailers = db.query(
        "SELECT real_name, company FROM users WHERE role='retailer' AND status='active' ORDER BY id")
    return render_template("panel/farmer_dashboard.html", batches=batches, stats=stats,
                           sales=sales, retailers=retailers)


# ---------------------------------------------------------------------------
# 加工商工作台
# ---------------------------------------------------------------------------
@bp.route("/contractor")
def contractor_dashboard():
    r = _guard("contractor")
    if r:
        return r
    batches = ts.list_batches(g.user["id"])
    # 可选入库的批次：所有尚未进入加工环节的批次
    available = [b for b in ts.list_batches() if b["current_stage"] == "farming"]
    sales = _seller_sales(g.user["id"])
    return render_template("panel/contractor_dashboard.html", batches=batches, available=available, sales=sales)


# ---------------------------------------------------------------------------
# 卖家商品管理（农户/加工商/物流公司）
# ---------------------------------------------------------------------------
@bp.route("/products")
def products():
    if not g.user or g.user["role"] not in ("farmer", "contractor", "logistics", "retailer", "admin"):
        return redirect(url_for("auth.login"))
    mine = ms.list_products(status="on_sale")
    my_products = [p for p in mine if p["seller_id"] == g.user["id"]]
    my_off = [p for p in ms.list_products(status="off_sale") if p["seller_id"] == g.user["id"]]
    return render_template("panel/products.html", products=my_products, off=my_off)


@bp.route("/products/create", methods=["POST"])
def product_create():
    if not g.user or g.user["role"] not in ("farmer", "contractor", "logistics", "retailer"):
        abort(403)
    ptype = request.form.get("product_type", "goods")
    batch_code = request.form.get("batch_code", "").strip() or None
    if ptype == "goods" and not batch_code:
        flash("实物商品必须关联一个溯源批次（溯源码）", "error")
        return redirect(url_for("panel.products"))
    p, err = ms.create_product(
        g.user,
        request.form.get("title", "").strip(),
        request.form.get("category", "其他").strip(),
        request.form.get("description", "").strip(),
        float(request.form.get("price", 0) or 0),
        float(request.form.get("stock", 0) or 0),
        request.form.get("unit", "kg").strip(),
        request.form.get("image", "🥬").strip(),
        product_type=ptype,
        batch_code=batch_code,
    )
    flash(err or f"商品「{p['title']}」上架成功，上架记录已上链", "success" if p else "error")
    return redirect(url_for("panel.products"))


@bp.route("/products/<int:pid>/update", methods=["POST"])
def product_update(pid):
    p = ms.get_product(pid)
    if not p or p["seller_id"] != g.user["id"]:
        abort(404)
    title = request.form.get("title", "").strip()
    if not title:
        flash("商品标题不能为空", "error")
        return redirect(url_for("panel.products"))
    db.execute(
        "UPDATE products SET title=?, price=?, stock=?, unit=?, description=? WHERE id=?",
        (title, float(request.form.get("price", 0) or 0),
         float(request.form.get("stock", 0) or 0),
         request.form.get("unit", "kg").strip(),
         request.form.get("description", "").strip(), pid),
    )
    flash("商品信息已更新", "success")
    return redirect(url_for("panel.products"))


@bp.route("/products/<int:pid>/toggle", methods=["POST"])
def product_toggle(pid):
    p = ms.get_product(pid)
    if not p or p["seller_id"] != g.user["id"]:
        abort(404)
    new_status = "off_sale" if p["status"] == "on_sale" else "on_sale"
    ms.set_product_status(pid, new_status)
    flash("已上架" if new_status == "on_sale" else "已下架", "success")
    return redirect(url_for("panel.products"))


# ---------------------------------------------------------------------------
# 二维码
# ---------------------------------------------------------------------------
@bp.route("/qrcode/<code>")
def qrcode(code):
    """生成溯源码二维码（SVG，需登录）。"""
    if not g.user:
        flash("请先登录", "error")
        return redirect(url_for("auth.login", next=f"/qrcode/{code}"))
    from flask import Response
    import qrcode
    import qrcode.image.svg
    from services.trace_service import get_batch_by_code
    b = get_batch_by_code(code)
    if not b:
        abort(404)
    factory = qrcode.image.svg.SvgPathImage
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=6, border=2)
    qr.add_data(request.host_url.rstrip("/") + url_for("trace.report", code=code))
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white", image_factory=factory)
    import io
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), mimetype="image/svg+xml")
