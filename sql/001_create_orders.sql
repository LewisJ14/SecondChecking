-- Schema for the consolidated marketplace order database.
-- Applies to MySQL 8.0+ so JSON columns and generated columns are available.

CREATE TABLE IF NOT EXISTS orders (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    local_id INT UNSIGNED NULL,
    platform VARCHAR(32) NOT NULL,
    external_id VARCHAR(128) NOT NULL,
    sku VARCHAR(128) NOT NULL,
    title VARCHAR(255) NULL,
    status VARCHAR(64) NULL,
    customer VARCHAR(255) NULL,
    total DECIMAL(10, 2) NULL,
    order_date DATETIME NULL,
    raw_data JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    -- Persist the zero-padded order number for compatibility with existing queries.
    order_number VARCHAR(16) AS (LPAD(COALESCE(local_id, id), 5, '0')) STORED,
    PRIMARY KEY (id),
    UNIQUE KEY uq_orders_local_id (local_id),
    UNIQUE KEY uq_orders_source_item (platform, external_id, sku),
    UNIQUE KEY uq_orders_order_number (order_number),
    KEY idx_orders_platform (platform)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS order_serials (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    order_id BIGINT UNSIGNED NOT NULL,
    order_number VARCHAR(16) NOT NULL,
    serial_number VARCHAR(64) NOT NULL,
    cpu VARCHAR(128) NULL,
    ram VARCHAR(64) NULL,
    ssd VARCHAR(64) NULL,
    model VARCHAR(128) NULL,
    resolution VARCHAR(64) NULL,
    windows VARCHAR(64) NULL,
    battery VARCHAR(64) NULL,
    test_keyboard ENUM('pass', 'fail', 'n/a') NOT NULL DEFAULT 'n/a',
    test_speaker ENUM('pass', 'fail', 'n/a') NOT NULL DEFAULT 'n/a',
    test_display ENUM('pass', 'fail', 'n/a') NOT NULL DEFAULT 'n/a',
    test_webcam ENUM('pass', 'fail', 'n/a') NOT NULL DEFAULT 'n/a',
    test_usb ENUM('pass', 'fail', 'n/a') NOT NULL DEFAULT 'n/a',
    activation ENUM('pass', 'fail', 'n/a') NOT NULL DEFAULT 'n/a',
    notes TEXT NULL,
    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_order_serial (order_id, serial_number),
    KEY idx_order_serials_order_number (order_number),
    KEY idx_order_serials_serial (serial_number),
    CONSTRAINT fk_order_serials_orders FOREIGN KEY (order_id)
        REFERENCES orders (id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
