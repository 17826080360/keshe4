-- =============================================================
-- 农产品溯源区块链系统 · 数据库 Schema
-- 三层数据模型：批次 batches → 环节 stages → 记录 records
-- 溯源与商城一体化：商品关联批次，订单明细携带溯源码
-- =============================================================

-- ---------- 用户 ----------
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL,               -- farmer 农户 / contractor 加工商 / logistics 物流 / retailer 零售商 / consumer 消费者 / admin 管理员
    real_name     TEXT NOT NULL,
    phone         TEXT,
    company       TEXT,
    address       TEXT,
    balance       REAL NOT NULL DEFAULT 0,     -- 钱包余额
    eth_address   TEXT,                        -- 链上账户地址（演示）
    status        TEXT NOT NULL DEFAULT 'active',
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ---------- 批次（三层模型·第一层）----------
CREATE TABLE IF NOT EXISTS batches (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_code    TEXT UNIQUE NOT NULL,        -- 溯源码，二维码内容
    product_name  TEXT NOT NULL,
    category      TEXT,
    origin        TEXT,
    description   TEXT,
    quantity      REAL NOT NULL DEFAULT 0,
    unit          TEXT NOT NULL DEFAULT 'kg',
    owner_id      INTEGER NOT NULL,            -- 建档人（农户/加工商）
    owner_role    TEXT NOT NULL,
    current_stage TEXT NOT NULL DEFAULT 'farming',  -- farming/processing/logistics/retail/sale
    status        TEXT NOT NULL DEFAULT 'in_progress', -- in_progress/completed
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ---------- 环节（三层模型·第二层）----------
CREATE TABLE IF NOT EXISTS stages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id   INTEGER NOT NULL,
    stage_type TEXT NOT NULL,                  -- farming 种养 / processing 加工 / logistics 物流 / retail 零售 / sale 销售
    stage_name TEXT,
    operator_id INTEGER,
    start_time TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    end_time   TEXT,
    status     TEXT NOT NULL DEFAULT 'active'
);

-- ---------- 记录（三层模型·第三层）----------
CREATE TABLE IF NOT EXISTS records (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id      INTEGER NOT NULL,
    stage_id      INTEGER,
    record_type   TEXT NOT NULL,               -- seed 种苗 / feed 饲料 / fertilize 施肥 / medicine 用药 / harvest 采摘捕捞 / warehouse 入库 / process 加工 / temperature 冷链温度 / track 运输轨迹 / list 上架 / sale 销售
    record_name   TEXT,
    content       TEXT NOT NULL,               -- JSON 文本，规范化后参与哈希
    operator_id   INTEGER,
    operator_name TEXT,
    data_hash     TEXT,                        -- 内容哈希（上链指纹）
    prev_hash     TEXT,                        -- 同批次上一条记录的哈希（哈希链）
    chain_status  TEXT NOT NULL DEFAULT 'pending', -- pending 待上链 / onchain 已上链 / failed 上链失败
    chain_tx      TEXT,                        -- 链上交易哈希
    chain_block   INTEGER,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ---------- 商城·商品 ----------
CREATE TABLE IF NOT EXISTS products (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id        INTEGER NOT NULL,
    seller_role      TEXT NOT NULL,
    product_type     TEXT NOT NULL DEFAULT 'goods', -- goods 实物商品 / service 物流服务
    title            TEXT NOT NULL,
    category         TEXT,
    description      TEXT,
    price            REAL NOT NULL,
    stock            REAL NOT NULL DEFAULT 0,
    unit             TEXT NOT NULL DEFAULT '件',
    image            TEXT DEFAULT '🥬',       -- emoji 商品图
    batch_id         INTEGER,                  -- 关联溯源批次
    source_product_id INTEGER,                 -- 转售来源商品
    status           TEXT NOT NULL DEFAULT 'on_sale', -- on_sale 在售 / off_sale 下架 / pending 待审核 / rejected 驳回
    sales_count      INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ---------- 商城·零售商库存 ----------
CREATE TABLE IF NOT EXISTS inventory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    retailer_id INTEGER NOT NULL,
    batch_id    INTEGER,
    product_id  INTEGER,
    quantity    REAL NOT NULL DEFAULT 0,
    unit        TEXT,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ---------- 商城·购物车 ----------
CREATE TABLE IF NOT EXISTS cart_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity   REAL NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ---------- 商城·订单 ----------
CREATE TABLE IF NOT EXISTS orders (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no          TEXT UNIQUE NOT NULL,
    buyer_id          INTEGER NOT NULL,
    seller_id         INTEGER NOT NULL,
    order_type        TEXT NOT NULL DEFAULT 'goods', -- goods 实物 / service 物流服务
    total_amount      REAL NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending_payment', -- pending_payment 待付款 / paid 已付款 / shipped 运输中 / completed 已完成 / cancelled 已取消
    shipping_address  TEXT,
    logistics_id      INTEGER,                 -- 承接物流公司
    tracking_no       TEXT,
    platform_fee      REAL NOT NULL DEFAULT 0, -- 平台手续费
    seller_income     REAL NOT NULL DEFAULT 0, -- 卖家实收
    remark            TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    paid_at           TEXT,
    shipped_at        TEXT,
    completed_at      TEXT
);

-- ---------- 商城·订单明细 ----------
CREATE TABLE IF NOT EXISTS order_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id     INTEGER NOT NULL,
    product_id   INTEGER,
    product_name TEXT,
    batch_id     INTEGER,
    trace_code   TEXT,                          -- 溯源码
    price        REAL,
    quantity     REAL,
    amount       REAL
);

-- ---------- 物流·运单 ----------
CREATE TABLE IF NOT EXISTS shipments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL,
    logistics_id INTEGER NOT NULL,              -- 物流公司
    tracking_no TEXT UNIQUE,
    status      TEXT NOT NULL DEFAULT 'pending', -- pending 待揽收 / picked_up 已揽收 / in_transit 运输中 / delivered 已送达
    cold_chain  INTEGER NOT NULL DEFAULT 1,      -- 是否冷链
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    picked_at   TEXT,
    delivered_at TEXT
);

-- ---------- 物流·冷链温度上报 ----------
CREATE TABLE IF NOT EXISTS temperature_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id  INTEGER NOT NULL,
    temperature  REAL NOT NULL,
    location     TEXT,
    data_hash    TEXT,
    chain_status TEXT NOT NULL DEFAULT 'pending',
    chain_tx     TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ---------- 物流·运输轨迹 ----------
CREATE TABLE IF NOT EXISTS track_points (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id INTEGER NOT NULL,
    location    TEXT,
    description TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ---------- 钱包流水 ----------
CREATE TABLE IF NOT EXISTS wallet_transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    amount        REAL NOT NULL,                -- 正数入账 / 负数支出
    balance_after REAL,
    tx_type       TEXT,                         -- recharge 充值 / pay 支付 / income 收入 / refund 退款
    related_order TEXT,
    remark        TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ---------- 篡改演示日志 ----------
CREATE TABLE IF NOT EXISTS tamper_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id  INTEGER,
    batch_id   INTEGER,
    record_type TEXT,
    old_content TEXT,
    new_content TEXT,
    operator   TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_records_batch  ON records(batch_id);
CREATE INDEX IF NOT EXISTS idx_records_hash   ON records(data_hash);
CREATE INDEX IF NOT EXISTS idx_stages_batch   ON stages(batch_id);
CREATE INDEX IF NOT EXISTS idx_products_seller ON products(seller_id);
CREATE INDEX IF NOT EXISTS idx_products_batch ON products(batch_id);
CREATE INDEX IF NOT EXISTS idx_orders_buyer   ON orders(buyer_id);
CREATE INDEX IF NOT EXISTS idx_orders_seller  ON orders(seller_id);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_shipments_order ON shipments(order_id);

CREATE TABLE IF NOT EXISTS order_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id   INTEGER NOT NULL,
    sender_id  INTEGER NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_messages_order ON order_messages(order_id);
