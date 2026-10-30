# -*- coding: utf-8 -*-
"""
演示种子数据：一条鲈鱼从养殖到上架再到销售的全流程 + 商城交易闭环。
含：农户养殖记录 → 加工商入库加工 → 零售进货 → 冷链物流 → 零售上架 → 消费者购买 → 全链上链。
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import db
from services import user_service, trace_service as ts, mall_service as ms
from blockchain.chain_backend import get_chain


def _backdate(table, row_id, days_ago=0, hours_ago=0):
    """把记录时间往回拨（created_at 仅展示用，不参与哈希）。"""
    ts_str = time.strftime("%Y-%m-%d %H:%M:%S",
                           time.localtime(time.time() - days_ago * 86400 - hours_ago * 3600))
    db.execute(f"UPDATE {table} SET created_at = ? WHERE id = ?", (ts_str, row_id))


def _users():
    u = {}
    for username, role, real_name, company in user_service.DEMO_ACCOUNTS:
        _, err = user_service.register(username, "123456", role, real_name, "13800000000",
                                       company, "武汉市 演示地址")
        u[username] = user_service.find_user(username)
    # 给买家/卖家充初始余额
    for name in ("farmer1", "contractor1", "logistics1", "retailer1", "consumer1"):
        user_service.recharge(u[name]["id"], 50000, "演示初始资金")
    return u


def _seed_fish_batch(u):
    """批次一：清江鲈鱼 完整链路。"""
    farmer = u["farmer1"]
    contractor = u["contractor1"]
    retailer = u["retailer1"]
    consumer = u["consumer1"]
    logistics = u["logistics1"]

    # ---------- 1. 农户建档 + 养殖记录 ----------
    batch = ts.create_batch(farmer, "清江鲈鱼", "水产", "湖北省宜昌市清江水库",
                            "水库网箱生态养殖，全程无违禁药物，扫码可查每一道环节。",
                            500, "kg")
    code = batch["batch_code"]
    ts.add_record(code, "seed", "种苗投放",
                  {"品种": "加州鲈鱼苗", "数量": "5000尾", "来源": "宜昌市水产良种场", "备注": "苗种检疫合格"}, farmer)
    ts.add_record(code, "feed", "饲料投喂",
                  {"饲料名称": "生态配合饲料", "用量": "日投喂120kg", "投喂时间": "每日06:00/18:00", "备注": "无激素"}, farmer)
    ts.add_record(code, "water", "水质检测",
                  {"检测项目": "溶解氧/pH/氨氮", "检测值": "6.8mg/L / 7.2 / 0.02mg/L", "标准范围": "溶氧≥5", "备注": "符合养殖水质标准"}, farmer)
    ts.add_record(code, "medicine", "用药记录",
                  {"药品名称": "聚维酮碘溶液(消毒)", "用量": "0.5ppm全池泼洒", "休药期(天)": "0", "备注": "休药期已满，无残留"}, farmer)
    ts.add_record(code, "harvest", "捕捞出塘",
                  {"数量": "500kg", "批次说明": "活鱼暂养2小时后排酸", "备注": "捕捞时间 05:30，全程低温"}, farmer)

    # ---------- 2. 加工商入库 + 加工 ----------
    ts.add_record(code, "warehouse", "批次入库",
                  {"入库数量": "500kg", "冷库温度": "-25℃", "供应商": "青山鱼塘（王大海）", "备注": "活鱼到厂即宰杀"}, contractor)
    ts.add_record(code, "process", "宰杀加工",
                  {"加工工序": "活鱼宰杀→去鳞→去内脏→冰水清洗", "加工方式": "0-4℃低温车间", "操作人": "陈师傅班组", "备注": "全程冷链"}, contractor)
    ts.add_record(code, "package", "真空包装",
                  {"包装方式": "真空锁鲜包装", "包装规格": "500g/袋", "生产日期": "当日", "备注": "标签印溯源码"}, contractor)

    # ---------- 3. 加工商上架商品 ----------
    p_fish = ms.create_product(contractor, "清江鲈鱼·真空锁鲜装", "水产",
                               "每袋溯源码可查：养殖→加工→冷链→零售全链路。", 30, 300, "kg", "🐟",
                               batch_code=code)[0]

    # ---------- 4. 零售商进货（批量采购） ----------
    o1, _ = ms.create_order(retailer, [(p_fish["id"], 100)], "鲜到家超市中心仓", "常规补货")
    ms.pay_order(o1["id"], retailer)
    ship1 = ms.ship_order(o1["id"], contractor, logistics["id"], ts.gen_tracking_no())
    # 物流：揽收 → 轨迹 → 温度 → 送达
    o1 = ms.get_order(o1["id"])
    ms.shipment_pickup(o1["shipment"]["id"], logistics["id"])
    ms.shipment_add_track(o1["shipment"]["id"], logistics["id"], "宜昌·鲜品加工厂", "冷柜装车，-18℃")
    ms.shipment_add_track(o1["shipment"]["id"], logistics["id"], "武汉·配送中心", "中转暂存，温度正常")
    for t in (-18.2, -17.9, -18.0, -18.5):
        ms.shipment_report_temp(o1["shipment"]["id"], logistics["id"], t, "冷链车 鄂A·C001")
    ms.shipment_deliver(o1["shipment"]["id"], logistics["id"])
    ms.confirm_receipt(o1["id"], retailer)  # 零售商确认收货 → 入库 + 销售上链

    # ---------- 5. 零售商转售上架 ----------
    inv = ms.list_inventory(retailer["id"])[0]
    p_resale = ms.retailer_resale(retailer, inv["id"], "清江鲈鱼·超市直供", 45, 60,
                                  "源头可溯：养殖批次 " + code + "，冷链到家，坏单包赔。", "🐟")[0]

    # ---------- 6. 消费者购买（扫码可溯） ----------
    o2, _ = ms.create_order(consumer, [(p_resale["id"], 2)], "光谷未来城 3栋 2单元 501", "周末家庭聚餐")
    ms.pay_order(o2["id"], consumer)
    ship2 = ms.ship_order(o2["id"], retailer, logistics["id"], ts.gen_tracking_no())
    o2 = ms.get_order(o2["id"])
    ms.shipment_pickup(o2["shipment"]["id"], logistics["id"])
    ms.shipment_add_track(o2["shipment"]["id"], logistics["id"], "武汉·鲜到家超市", "骑手取件，保温箱配送")
    ms.shipment_add_track(o2["shipment"]["id"], logistics["id"], "武汉·光谷未来城", "已到达配送点")
    ms.shipment_report_temp(o2["shipment"]["id"], logistics["id"], -18.3, "同城冷链箱")
    ms.shipment_deliver(o2["shipment"]["id"], logistics["id"])
    ms.confirm_receipt(o2["id"], consumer)  # 消费者确认收货 → 销售上链

    # 回溯时间线（展示用）
    recs = ts.get_records(batch["id"])
    base_days = 30
    for i, r in enumerate(recs):
        _backdate("records", r["id"], days_ago=max(0, base_days - i * 4))
    _backdate("batches", batch["id"], days_ago=31)
    return batch


def _seed_veg_batch(u):
    """批次二：有机蔬菜（农户直接零售，展示多元卖家）。"""
    farmer = u["farmer1"]
    consumer = u["consumer1"]
    logistics = u["logistics1"]
    batch = ts.create_batch(farmer, "有机菠菜", "蔬菜", "武汉新洲区有机农场",
                            "有机认证种植，施用农家肥，无化学农药。", 200, "kg")
    code = batch["batch_code"]
    ts.add_record(code, "seed", "播种", {"品种": "大叶菠菜", "面积": "2亩", "备注": "有机种子"}, farmer)
    ts.add_record(code, "fertilize", "施肥", {"肥料名称": "腐熟农家肥", "用量": "每亩800kg", "备注": "有机肥"}, farmer)
    ts.add_record(code, "water", "土壤检测", {"检测项目": "农残/重金属", "检测值": "未检出", "标准范围": "国标合格线以下", "备注": "检测报告编号 HJ2026-0417"}, farmer)
    ts.add_record(code, "harvest", "采收", {"数量": "200kg", "备注": "清晨采收，全程遮阳"}, farmer)

    p = ms.create_product(farmer, "有机菠菜·当季现摘", "蔬菜", "产地直发，可溯源码查看种植全记录。", 8, 200, "kg", "🥬", batch_code=code)[0]
    # 消费者直接向农户购买
    o, _ = ms.create_order(consumer, [(p["id"], 5)], "光谷未来城 3栋 2单元 501", "尝鲜")
    ms.pay_order(o["id"], consumer)
    ms.ship_order(o["id"], farmer, logistics["id"], ts.gen_tracking_no())
    o = ms.get_order(o["id"])
    ms.shipment_pickup(o["shipment"]["id"], logistics["id"])
    ms.shipment_add_track(o["shipment"]["id"], logistics["id"], "武汉·新洲有机农场", "常温箱装车")
    ms.shipment_deliver(o["shipment"]["id"], logistics["id"])
    ms.confirm_receipt(o["id"], consumer)

    recs = ts.get_records(batch["id"])
    for i, r in enumerate(recs):
        _backdate("records", r["id"], days_ago=max(0, 12 - i * 2))
    _backdate("batches", batch["id"], days_ago=13)
    return batch


def _seed_service(u):
    """物流服务商品 + 一笔已完成的服务订单。"""
    logistics = u["logistics1"]
    consumer = u["consumer1"]
    p = ms.create_product(logistics, "同城冷链配送服务", "物流服务",
                          "专业冷链箱配送，全程温度可溯，每单20元。", 20, 9999, "单", "🚚",
                          product_type="service")[0]
    o, _ = ms.create_order(consumer, [(p["id"], 1)], "光谷未来城 3栋 2单元 501", "预约周末配送")
    ms.pay_order(o["id"], consumer)
    ms.complete_service(o["id"], logistics)
    return p


def seed_all():
    print("[种子] 正在生成演示数据……")
    chain = get_chain()
    if chain.active == "ganache":
        print("[种子] 使用 Ganache 真实链上链")
    else:
        print("[种子] 使用本地模拟链上链（无 Ganache 时自动启用）")

    u = _users()
    b1 = _seed_fish_batch(u)
    b2 = _seed_veg_batch(u)
    _seed_service(u)

    # 商品目录中再补两个已上链的商品供选购
    farmer = u["farmer1"]
    contractor = u["contractor1"]
    veg = db.query("SELECT id FROM batches ORDER BY id DESC LIMIT 1", one=True)
    print("[种子] 演示数据就绪：")
    print(f"   - 批次1（鲈鱼全链路）：{b1['batch_code']}")
    print(f"   - 批次2（有机菠菜）：{b2['batch_code']}")
    print("   - 演示账号：admin / farmer1 / contractor1 / logistics1 / retailer1 / consumer1（密码 123456）")


def ensure_seeded():
    """幂等：已有用户则跳过。"""
    c = db.query("SELECT COUNT(*) c FROM users", one=True)["c"]
    if c == 0:
        seed_all()
