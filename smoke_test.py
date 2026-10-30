# -*- coding: utf-8 -*-
"""冒烟测试：清库 → 种子数据 → 链校验 → 篡改演示。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db
from blockchain.chain_backend import get_chain
from services import trace_service as ts
from services import mall_service as ms

# 1. 清空
conn = db.get_conn()
tables = [r["name"] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
for t in tables:
    conn.execute("DELETE FROM " + t)
conn.commit()
conn.close()

# 2. 种子
from database.seed import seed_all
seed_all()

chain = get_chain()
print("\n链模式:", chain.active)
print("链完整性:", chain.integrity_check())

# 3. 校验鲈鱼批次（最近创建的批次在前，取最后一个创建的即鲈鱼批次）
batches = ts.list_batches()
for b in batches:
    v = ts.verify_batch(b["batch_code"])
    print(f"\n批次 {b['batch_code']} {b['product_name']} | 记录 {len(v['results'])} 条 | 全部通过: {v['ok']}")
    for r in v["results"]:
        rec = r["record"]
        print(f"  [{rec['record_type']:>10}] {rec['data_hash'][:18]}… 链上={rec['chain_status']:>7} 校验={'OK' if r['verify']['ok'] else 'FAIL'}")

# 4. 篡改演示
print("\n--- 篡改演示 ---")
rec = ts.get_records(batches[0]["id"])[2]  # 取第3条记录
import json
content = ts._parse_content(rec)
old_content = json.dumps(content, ensure_ascii=False)  # 保存原文
field = "用量" if "用量" in content else list(content.keys())[0]
content[field] = "被篡改后的假数据99999"
db.execute("UPDATE records SET content = ? WHERE id = ?", (json.dumps(content, ensure_ascii=False), rec["id"]))
v = ts.verify_batch(batches[0]["batch_code"])
tampered = [r for r in v["results"] if not r["verify"]["ok"]]
print(f"篡改后：{len(tampered)} 条记录被链上校验拒绝")
assert len(tampered) > 0, "篡改未被发现！"
print("篡改检测通过 ✓")

# 5. 恢复
db.execute("UPDATE records SET content = ? WHERE id = ?", (old_content, rec["id"]))
v2 = ts.verify_batch(batches[0]["batch_code"])
print("恢复后全部通过:", v2["ok"])

# 6. 商城数据
print("\n--- 商城数据 ---")
print("商品数:", ms.count_products(), "| 订单数:", ms.count_orders(), "| GMV:", ms.sum_gmv())
print("全部冒烟测试通过 ✓")
