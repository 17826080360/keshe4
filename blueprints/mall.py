# -*- coding: utf-8 -*-
"""商城路由：商品、购物车、下单、订单、物流、库存转售。"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g, abort

from services import mall_service as ms
from services import user_service
from services import trace_service as ts

bp = Blueprint("mall", __name__)


def _login_required():
    if not g.user:
        flash("请先登录", "error")
        return redirect(url_for("auth.login"))
    return None


# ---------------------------------------------------------------------------
# 商品浏览
# ---------------------------------------------------------------------------
@bp.route("/mall")
def index():
    category = request.args.get("category", "全部")
    seller_role = request.args.get("seller_role", "全部")
    keyword = request.args.get("keyword", "").strip()
    ptype = request.args.get("type", "全部")
    products = ms.list_products(category=category, seller_role=seller_role, keyword=keyword, product_type=ptype)
    cats = ms.categories()
    return render_template("mall/list.html", products=products, cats=cats,
                           category=category, seller_role=seller_role, keyword=keyword, ptype=ptype)


@bp.route("/mall/<int:pid>")
def detail(pid):
    p = ms.get_product(pid)
    if not p or p["status"] not in ("on_sale", "off_sale"):
        abort(404)
    batch_ok = None
    if p["batch"]:
        v = ts.verify_batch(p["batch"]["batch_code"])
        batch_ok = v["ok"] if v else None
    return render_template("mall/detail.html", p=p, batch_ok=batch_ok)


# ---------------------------------------------------------------------------
# 购物车
# ---------------------------------------------------------------------------
@bp.route("/cart")
def cart():
    if _login_required():
        return _login_required()
    rows, total = ms.get_cart(g.user["id"])
    return render_template("mall/cart.html", rows=rows, total=total)


@bp.route("/cart/add", methods=["POST"])
def cart_add():
    if _login_required():
        return _login_required()
    pid = int(request.form.get("product_id", 0))
    qty = float(request.form.get("quantity", 1))
    ok, err = ms.add_cart(g.user["id"], pid, qty)
    flash(err or "已加入购物车", "success" if ok else "error")
    return redirect(request.referrer or url_for("mall.detail", pid=pid))


@bp.route("/cart/update", methods=["POST"])
def cart_update():
    if _login_required():
        return _login_required()
    for key, val in request.form.items():
        if key.startswith("qty_"):
            ms.update_cart_item(int(key[4:]), float(val))
    flash("购物车已更新", "success")
    return redirect(url_for("mall.cart"))


# ---------------------------------------------------------------------------
# 下单与支付
# ---------------------------------------------------------------------------
@bp.route("/checkout", methods=["GET", "POST"])
def checkout():
    if _login_required():
        return _login_required()
    if request.method == "POST":
        address = request.form.get("address", "").strip()
        remark = request.form.get("remark", "").strip()
        buy_now_pid = request.form.get("buy_now")
        qty = float(request.form.get("quantity", 1))
        if buy_now_pid:
            items = [(int(buy_now_pid), qty)]
        else:
            rows, _ = ms.get_cart(g.user["id"])
            items = [(r["product_id"], r["quantity"]) for r in rows]
        if not items:
            flash("请先选择商品", "error")
            return redirect(url_for("mall.index"))
        o, err = ms.create_order(g.user, items, address or g.user["address"] or "默认收货地址", remark)
        if err:
            flash(err, "error")
            return redirect(url_for("mall.cart") if not buy_now_pid else url_for("mall.detail", pid=int(buy_now_pid)))
        return redirect(url_for("mall.order_detail", oid=o["id"]))
    rows, total = ms.get_cart(g.user["id"])
    return render_template("mall/checkout.html", rows=rows, total=total)


@bp.route("/order/<int:oid>")
def order_detail(oid):
    if _login_required():
        return _login_required()
    o = ms.get_order(oid)
    if not o:
        abort(404)
    if g.user["id"] not in (o["buyer_id"], o["seller_id"]) and g.user["role"] != "admin":
        abort(403)
    logistics_list = ms.list_logistics_companies() if o["seller_id"] == g.user["id"] else []
    messages = ms.list_messages(oid)
    return render_template("mall/order_detail.html", o=o, logistics_list=logistics_list, messages=messages)


@bp.route("/messages")
def messages():
    if _login_required():
        return _login_required()
    convs = ms.list_conversations(g.user["id"])
    my_orders = ms.list_buyer_orders(g.user["id"])
    return render_template("mall/messages.html", convs=convs, my_orders=my_orders)


@bp.route("/order/<int:oid>/message", methods=["POST"])
def order_message(oid):
    o = ms.get_order(oid)
    if not o:
        abort(404)
    if g.user["id"] not in (o["buyer_id"], o["seller_id"]) and g.user["role"] != "admin":
        abort(403)
    ms.add_message(oid, g.user["id"], request.form.get("content", ""))
    nxt = request.form.get("next") or request.args.get("next")
    if nxt and nxt.startswith("/"):
        return redirect(nxt)
    return redirect(url_for("mall.order_detail", oid=oid))


@bp.route("/order/<int:oid>/pay", methods=["POST"])
def order_pay(oid):
    if _login_required():
        return _login_required()
    ok, err = ms.pay_order(oid, g.user)
    if ok:
        o = ms.get_order(oid)
        ms.add_message(oid, o["seller_id"],
            "✅ 订单已收到！我们会尽快备货并安排冷链发货，有任何问题随时联系我。")
    flash(err or "支付成功，货款已进入平台托管，收货后结算给卖家", "success" if ok else "error")
    return redirect(url_for("mall.order_detail", oid=oid))


@bp.route("/order/<int:oid>/cancel", methods=["POST"])
def order_cancel(oid):
    if _login_required():
        return _login_required()
    ok, err = ms.cancel_order(oid, g.user)
    flash(err or "订单已取消，库存已归还", "success" if ok else "error")
    return redirect(url_for("mall.order_detail", oid=oid))


@bp.route("/order/<int:oid>/ship", methods=["POST"])
def order_ship(oid):
    if _login_required():
        return _login_required()
    logistics_id = int(request.form.get("logistics_id", 0))
    tracking_no = request.form.get("tracking_no", "").strip() or ts.gen_tracking_no()
    ok, err = ms.ship_order(oid, g.user, logistics_id, tracking_no)
    if ok:
        o = ms.get_order(oid)
        ms.add_message(oid, o["seller_id"],
            f"📦 已为您发货！运单号 {tracking_no}，全程冷链运输中，到货后请及时确认收货。")
    flash(err or f"发货成功，运单号 {tracking_no}，物流事件已上链", "success" if ok else "error")
    return redirect(url_for("mall.order_detail", oid=oid))


@bp.route("/order/<int:oid>/confirm", methods=["POST"])
def order_confirm(oid):
    if _login_required():
        return _login_required()
    ok, err = ms.confirm_receipt(oid, g.user)
    flash(err or "确认收货成功，资金已结算给卖家，销售记录已上链", "success" if ok else "error")
    return redirect(url_for("mall.order_detail", oid=oid))


@bp.route("/order/<int:oid>/complete_service", methods=["POST"])
def order_complete_service(oid):
    if _login_required():
        return _login_required()
    ok, err = ms.complete_service(oid, g.user)
    flash(err or "服务已完成，资金已结算", "success" if ok else "error")
    return redirect(url_for("mall.order_detail", oid=oid))


@bp.route("/orders")
def orders():
    if _login_required():
        return _login_required()
    side = request.args.get("side", "buy")
    status = request.args.get("status", "全部")
    rows = ms.list_orders(g.user["id"], side=side, status=status)
    return render_template("mall/orders.html", rows=rows, side=side, status=status)


# ---------------------------------------------------------------------------
# 物流公司：运单操作
# ---------------------------------------------------------------------------
@bp.route("/logistics/shipments")
def logistics_shipments():
    if _login_required():
        return _login_required()
    if g.user["role"] != "logistics":
        abort(403)
    status = request.args.get("status", "全部")
    rows = ms.list_shipments(g.user["id"], status=status)
    return render_template("panel/logistics_shipments.html", rows=rows, status=status)


@bp.route("/logistics/shipment/<int:sid>")
def logistics_shipment_detail(sid):
    if _login_required():
        return _login_required()
    s = ms.get_shipment(sid)
    if not s or s["logistics_id"] != g.user["id"]:
        abort(404)
    return render_template("panel/logistics_shipment_detail.html", s=s)


@bp.route("/logistics/shipment/<int:sid>/pickup", methods=["POST"])
def logistics_pickup(sid):
    if _login_required():
        return _login_required()
    ok, err = ms.shipment_pickup(sid, g.user["id"])
    flash(err or "已揽收", "success" if ok else "error")
    return redirect(url_for("mall.logistics_shipment_detail", sid=sid))


@bp.route("/logistics/shipment/<int:sid>/track", methods=["POST"])
def logistics_track(sid):
    if _login_required():
        return _login_required()
    location = request.form.get("location", "").strip()
    description = request.form.get("description", "").strip()
    ok, err = ms.shipment_add_track(sid, g.user["id"], location, description)
    flash(err or "轨迹已上报并上链", "success" if ok else "error")
    return redirect(url_for("mall.logistics_shipment_detail", sid=sid))


@bp.route("/logistics/shipment/<int:sid>/temp", methods=["POST"])
def logistics_temp(sid):
    if _login_required():
        return _login_required()
    temperature = float(request.form.get("temperature", 0))
    location = request.form.get("location", "").strip()
    ok, err = ms.shipment_report_temp(sid, g.user["id"], temperature, location)
    flash(err or "冷链温度已上报并上链", "success" if ok else "error")
    return redirect(url_for("mall.logistics_shipment_detail", sid=sid))


@bp.route("/logistics/shipment/<int:sid>/deliver", methods=["POST"])
def logistics_deliver(sid):
    if _login_required():
        return _login_required()
    ok, err = ms.shipment_deliver(sid, g.user["id"])
    flash(err or "已送达，等待买家确认收货", "success" if ok else "error")
    return redirect(url_for("mall.logistics_shipment_detail", sid=sid))


# ---------------------------------------------------------------------------
# 零售商：库存与转售
# ---------------------------------------------------------------------------
@bp.route("/retailer/inventory")
def retailer_inventory():
    if _login_required():
        return _login_required()
    if g.user["role"] != "retailer":
        abort(403)
    inv = ms.list_inventory(g.user["id"])
    supplies = [x for x in ms.list_products(status="on_sale")
                if x["seller_role"] in ("farmer", "contractor")]
    return render_template("panel/retailer_inventory.html", inv=inv, supplies=supplies)


@bp.route("/retailer/resale/<int:inv_id>", methods=["POST"])
def retailer_resale(inv_id):
    if _login_required():
        return _login_required()
    title = request.form.get("title", "").strip()
    price = float(request.form.get("price", 0))
    qty = float(request.form.get("quantity", 0))
    description = request.form.get("description", "").strip()
    image = request.form.get("image", "🥬").strip()
    p, err = ms.retailer_resale(g.user, inv_id, title, price, qty, description, image)
    flash(err or f"商品「{title}」已上架，可继续溯源", "success" if p else "error")
    return redirect(url_for("mall.retailer_inventory"))
