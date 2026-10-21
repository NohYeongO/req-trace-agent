-- 테스트용 DDL
CREATE TABLE IF NOT EXISTS carts (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    account_id BIGINT NOT NULL COMMENT '계정 ID',
    created_at DATETIME(6)
);

CREATE TABLE IF NOT EXISTS cart_items (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    cart_id BIGINT NOT NULL,
    product_id BIGINT NOT NULL,
    quantity INT,
    status VARCHAR(20),
    created_at DATETIME(6),
    legacy_flag BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (cart_id) REFERENCES carts(id),
    CONSTRAINT uk_cart_product UNIQUE (cart_id, product_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGINT PRIMARY KEY
);
