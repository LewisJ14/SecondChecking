-- Schema for the consolidated marketplace order database.
-- Applies to MySQL 8.0+ so JSON columns and generated columns are available.

CREATE TABLE IF NOT EXISTS `order` (
    id INT NOT NULL AUTO_INCREMENT,
    local_id INT NULL,
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
    PRIMARY KEY (id),
    UNIQUE KEY uq_order_local_id (local_id),
    UNIQUE KEY uq_order_source_item (platform, external_id, sku),
    KEY idx_order_platform (platform)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Display order numbers are produced in application logic using
-- LPAD(COALESCE(local_id, id), 5, '0').

CREATE TABLE IF NOT EXISTS `order_serials` (
    id BIGINT NOT NULL AUTO_INCREMENT,
    order_id INT NOT NULL,
    order_number VARCHAR(64) NOT NULL,
    serial_number VARCHAR(64) NOT NULL,
    sku VARCHAR(128) NULL,
    cpu VARCHAR(128) NULL,
    ram VARCHAR(128) NULL,
    ssd VARCHAR(128) NULL,
    model VARCHAR(128) NULL,
    resolution VARCHAR(128) NULL,
    windows VARCHAR(128) NULL,
    battery VARCHAR(128) NULL,
    battery2 VARCHAR(128) NULL,
    test_keyboard VARCHAR(16) NULL,
    test_speaker VARCHAR(16) NULL,
    test_microphone VARCHAR(16) NULL,
    test_display VARCHAR(16) NULL,
    test_webcam VARCHAR(16) NULL,
    test_usb VARCHAR(16) NULL,
    activation VARCHAR(16) NULL,
    mdm_state VARCHAR(32) NULL,
    mdm_details TEXT NULL,
    assigned_by VARCHAR(150) NULL,
    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uniq_serial_number (serial_number),
    KEY idx_order_serials_order_id (order_id),
    KEY idx_order_serials_order_number (order_number),
    KEY idx_order_serials_sku (sku),
    CONSTRAINT fk_order_serials_order FOREIGN KEY (order_id)
        REFERENCES `order`(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `user` (
    id INT NOT NULL AUTO_INCREMENT,
    email VARCHAR(150) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT "user",
    username VARCHAR(150) NOT NULL,
    password_hash VARCHAR(512) NOT NULL,
    must_reset_password BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_user_email (email),
    UNIQUE KEY uq_user_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
