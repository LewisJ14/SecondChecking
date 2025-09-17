CREATE TABLE IF NOT EXISTS `order` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `order_number` VARCHAR(64) NOT NULL,
    `status` VARCHAR(32) NOT NULL,
    `customer_id` BIGINT,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uniq_order_number` (`order_number`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `order_serials` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `order_id` INT NOT NULL,
    `order_number` VARCHAR(64) NOT NULL,
    `serial_number` VARCHAR(64) NOT NULL,
    `cpu` VARCHAR(128),
    `ram` VARCHAR(128),
    `ssd` VARCHAR(128),
    `model` VARCHAR(128),
    `resolution` VARCHAR(128),
    `windows` VARCHAR(128),
    `battery` VARCHAR(128),
    `test_keyboard` VARCHAR(16),
    `test_speaker` VARCHAR(16),
    `test_display` VARCHAR(16),
    `test_webcam` VARCHAR(16),
    `test_usb` VARCHAR(16),
    `activation` VARCHAR(16),
    `assigned_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uniq_serial_number` (`serial_number`),
    KEY `idx_order_serials_order_id` (`order_id`),
    CONSTRAINT `fk_order_serials_order`
        FOREIGN KEY (`order_id`) REFERENCES `order` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
