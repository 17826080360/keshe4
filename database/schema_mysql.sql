-- =============================================================
-- 农产品溯源区块链系统 · MySQL Schema
-- =============================================================

CREATE TABLE IF NOT EXISTS users (
    id            INT PRIMARY KEY AUTO_INCREMENT,
    username      VARCHAR(64) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role          VARCHAR(32) NOT NULL,
    real_name     VARCHAR(64) NOT NULL,
    phone         VARCHAR(32),
    company       VARCHAR(128),
    address       VARCHAR(255),
    balance       DOUBLE NOT NULL DEFAULT 0,
    eth_address   VARCHAR(128),
    status        VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS batches (
    id            INT PRIMARY KEY AUTO_INCREMENT,
    batch_code    VARCHAR(64) UNIQUE NOT NULL,
    product_name  VARCHAR(128) NOT NULL,
    category      VARCHAR(64),
    origin        VARCHAR(128),
    description   TEXT,
    quantity      DOUBLE NOT NULL DEFAULT 0,
    unit          VARCHAR(16) NOT NULL DEFAULT 'kg',
    owner_id      INT NOT NULL,
    owner_role    VARCHAR(32) NOT NULL,
    current_stage VARCHAR(32) NOT NULL DEFAULT 'farming',
    status        VARCHAR(32) NOT NULL DEFAULT 'in_progress',
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS stages (
    id         INT PRIMARY KEY AUTO_INCREMENT,
    batch_id   INT NOT NULL,
    stage_type VARCHAR(32) NOT NULL,
    stage_name VARCHAR(64),
    operator_id INT,
    start_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    end_time   DATETIME NULL,
    status     VARCHAR(16) NOT NULL DEFAULT 'active'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS records (
    id            INT PRIMARY KEY AUTO_INCREMENT,
    batch_id      INT NOT NULL,
    stage_id      INT,
    record_type   VARCHAR(32) NOT NULL,
    record_name   VARCHAR(128),
    content       TEXT NOT NULL,
    operator_id   INT,
    operator_name VARCHAR(64),
    data_hash     VARCHAR(128),
    prev_hash     VARCHAR(128),
    chain_status  VARCHAR(16) NOT NULL DEFAULT 'pending',
    chain_tx      VARCHAR(128),
    chain_block   INT,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS products (
    id               INT PRIMARY KEY AUTO_INCREMENT,
    seller_id        INT NOT NULL,
    seller_role      VARCHAR(32) NOT NULL,
    product_type     VARCHAR(16) NOT NULL DEFAULT 'goods',
    title            VARCHAR(128) NOT NULL,
    category         VARCHAR(64),
    description      TEXT,
    price            DOUBLE NOT NULL,
    stock            DOUBLE NOT NULL DEFAULT 0,
    unit             VARCHAR(16) NOT NULL DEFAULT '件',
    image            VARCHAR(16) DEFAULT '🥬',
    batch_id         INT,
    source_product_id INT,
    status           VARCHAR(16) NOT NULL DEFAULT 'on_sale',
    sales_count      INT NOT NULL DEFAULT 0,
    created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS inventory (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    retailer_id INT NOT NULL,
    batch_id    INT,
    product_id  INT,
    quantity    DOUBLE NOT NULL DEFAULT 0,
    unit        VARCHAR(16),
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS cart_items (
    id         INT PRIMARY KEY AUTO_INCREMENT,
    user_id    INT NOT NULL,
    product_id INT NOT NULL,
    quantity   DOUBLE NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS orders (
    id                INT PRIMARY KEY AUTO_INCREMENT,
    order_no          VARCHAR(64) UNIQUE NOT NULL,
    buyer_id          INT NOT NULL,
    seller_id         INT NOT NULL,
    order_type        VARCHAR(16) NOT NULL DEFAULT 'goods',
    total_amount      DOUBLE NOT NULL,
    status            VARCHAR(32) NOT NULL DEFAULT 'pending_payment',
    shipping_address  VARCHAR(255),
    logistics_id      INT,
    tracking_no       VARCHAR(64),
    platform_fee      DOUBLE NOT NULL DEFAULT 0,
    seller_income     DOUBLE NOT NULL DEFAULT 0,
    remark            VARCHAR(255),
    created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    paid_at           DATETIME NULL,
    shipped_at        DATETIME NULL,
    completed_at      DATETIME NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS order_items (
    id           INT PRIMARY KEY AUTO_INCREMENT,
    order_id     INT NOT NULL,
    product_id   INT,
    product_name VARCHAR(128),
    batch_id     INT,
    trace_code   VARCHAR(64),
    price        DOUBLE,
    quantity     DOUBLE,
    amount       DOUBLE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS shipments (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    order_id    INT NOT NULL,
    logistics_id INT NOT NULL,
    tracking_no VARCHAR(64) UNIQUE,
    status      VARCHAR(32) NOT NULL DEFAULT 'pending',
    cold_chain  INT NOT NULL DEFAULT 1,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    picked_at   DATETIME NULL,
    delivered_at DATETIME NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS temperature_logs (
    id           INT PRIMARY KEY AUTO_INCREMENT,
    shipment_id  INT NOT NULL,
    temperature  DOUBLE NOT NULL,
    location     VARCHAR(128),
    data_hash    VARCHAR(128),
    chain_status VARCHAR(16) NOT NULL DEFAULT 'pending',
    chain_tx     VARCHAR(128),
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS track_points (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    shipment_id INT NOT NULL,
    location    VARCHAR(128),
    description VARCHAR(255),
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wallet_transactions (
    id            INT PRIMARY KEY AUTO_INCREMENT,
    user_id       INT NOT NULL,
    amount        DOUBLE NOT NULL,
    balance_after DOUBLE,
    tx_type       VARCHAR(32),
    related_order VARCHAR(64),
    remark        VARCHAR(255),
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS tamper_logs (
    id         INT PRIMARY KEY AUTO_INCREMENT,
    record_id  INT,
    batch_id   INT,
    record_type VARCHAR(32),
    old_content TEXT,
    new_content TEXT,
    operator   VARCHAR(64),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS order_messages (
    id         INT PRIMARY KEY AUTO_INCREMENT,
    order_id   INT NOT NULL,
    sender_id  INT NOT NULL,
    content    TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_records_batch  ON records(batch_id);
CREATE INDEX idx_records_hash   ON records(data_hash);
CREATE INDEX idx_stages_batch   ON stages(batch_id);
CREATE INDEX idx_products_seller ON products(seller_id);
CREATE INDEX idx_products_batch ON products(batch_id);
CREATE INDEX idx_orders_buyer   ON orders(buyer_id);
CREATE INDEX idx_orders_seller  ON orders(seller_id);
CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE INDEX idx_shipments_order ON shipments(order_id);
CREATE INDEX idx_messages_order ON order_messages(order_id);
