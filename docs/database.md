# Database schema

This application consolidates eBay and WooCommerce orders inside a single MySQL
schema. Orders are stored once in the `order` table, while assigned device
serials, recorded hardware tests, and captured specification details live in
`order_serials`. The SQL required to provision both tables is provided in
[`sql/001_create_order.sql`](../sql/001_create_order.sql).

## `order`

The `order` table captures the marketplace metadata for each line item so the
application can look up an SKU regardless of the marketplace that produced it.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INT` | Surrogate primary key for internal joins. |
| `local_id` | `INT` | Optional sequential identifier used for human friendly numbering. |
| `platform` | `VARCHAR(32)` | Marketplace identifier such as `ebay` or `woocommerce`. |
| `external_id` | `VARCHAR(128)` | Order reference from the originating marketplace. |
| `sku` | `VARCHAR(128)` | SKU for the individual line item; multiple rows can exist per order. |
| `title`, `status`, `customer` | `VARCHAR` fields | Optional descriptive metadata displayed in the UI. |
| `total` | `DECIMAL(10,2)` | Monetary total reported by the marketplace. |
| `order_date` | `DATETIME` | Timestamp from the marketplace payload. |
| `raw_data` | `JSON` | Full raw connector payload for auditing and reprocessing. |
| `created_at`, `updated_at` | `DATETIME` | Automatic timestamps tracking inserts and updates. |
| `order_number` (virtual) | derived property | Within the application layer `LPAD(COALESCE(local_id, id), 5, '0')` is exposed as `order_number` so the UI can render five-digit identifiers (for example `00001`). |

Additional integrity rules:

- A unique constraint on `(platform, external_id, sku)` prevents duplicate line
  items when syncing the same order multiple times.
- `local_id` is unique so the UI can safely display `00001`, `00002`, etc.
  using the derived `order_number` property without gaps.
- An index on `platform` keeps marketplace specific lookups fast.

## `order_serials`

Each physical device that has been matched to an order is tracked in the
`order_serials` table along with the specification snapshot and recorded test
results.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `BIGINT` | Surrogate primary key. |
| `order_id` | `INT` | Foreign key pointing at `order.id`. |
| `order_number` | `VARCHAR(64)` | Cached string used by the existing UI for lookups without an extra join. |
| `serial_number` | `VARCHAR(64)` | Unique hardware identifier. |
| `sku` | `VARCHAR(128)` | SKU selected during assignment so later views can display the matched item. |
| `cpu`, `ram`, `ssd`, `model`, `resolution`, `windows`, `battery` | `VARCHAR(128)` | Specification snapshot captured when the device was assigned. |
| `test_keyboard`, `test_speaker`, `test_microphone`, `test_display`, `test_webcam`, `test_usb`, `activation` | `VARCHAR(16)` | Stored test outcomes normalised to `pass`, `fail`, or `n/a`. |
| `assigned_at` | `DATETIME` | Timestamp capturing when the serial was linked to the order. |

`order_serials` enforces a unique serial number so a device can only appear once
in the table. Indexes on `order_id`, `order_number`, and `sku` support the
direct lookup paths used by the current application logic. The foreign key
inherits cascade rules from `order` so removing an order automatically clears
related serial assignments.

## Applying the schema

Run the statements in [`sql/001_create_order.sql`](../sql/001_create_order.sql)
against your MySQL instance to migrate to the consolidated schema:

```sql
SOURCE sql/001_create_order.sql;
```

When running directly from a shell, you can feed the schema file into MySQL in
one step (replace the placeholders with your credentials):

```bash
MYSQL_PWD="${DB_PASSWORD}" mysql -h "$DB_HOST" -u "$DB_USER" "$DB_NAME" < sql/001_create_order.sql
```

The script uses `CREATE TABLE IF NOT EXISTS`, making it safe to execute during
initial provisioning or incremental deployments.
