"""Read-only contract for the desktop's direct database operations."""
SCHEMA_CONTRACT_VERSION = 2
MINIMUM_SERVER_MIGRATION = "0d9e0f1a2b3c"
REQUIRED_COLUMNS = {
    "order": {"id", "order_number", "external_id", "sku"},
    "order_serials": {"order_id", "order_number", "serial_number", "sku",
                      "assigned_at", "test_keyboard", "test_speaker",
                      "test_microphone", "test_display", "test_webcam",
                      "test_usb", "test_wifi", "battery", "battery2",
                      "mdm_state", "mdm_details", "assigned_by", "laptop_status"},
    "order_note": {"order_id", "notes", "created_at", "updated_at"},
    "custom_order_item": {"id", "order_id", "spec_set", "line_number", "sku",
                          "title", "model_label", "cpu", "os", "ram", "ssd",
                          "battery"},
    "dropdown_option": {"id", "category", "name"},
    "attribute_term_metadata": {"attribute_id", "term_id", "sku_tag",
                                "astro_name", "dropdown_option_id"},
    "attribute_dropdown_map": {"attribute_id", "dropdown_category"},
    "sku_detection_rule": {"id", "category", "sku_tag", "detected_value",
                           "priority", "enabled"},
}


class SchemaCompatibilityError(RuntimeError):
    """Safe operator-facing failure; contains only our contract identifiers."""


def validate_schema(conn, database_name):
    """Reject incomplete/invisible schemas without writing or committing."""
    tables = sorted(REQUIRED_COLUMNS)
    placeholders = ", ".join(["%s"] * len(tables))
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name IN (" + placeholders + ")",
                (database_name, *tables))
            rows = cursor.fetchall()
        existing = {}
        for table, column in rows:
            if isinstance(table, bytes):
                table = table.decode("utf-8")
            if isinstance(column, bytes):
                column = column.decode("utf-8")
            existing.setdefault(table, set()).add(column)
    except Exception:
        raise SchemaCompatibilityError(
            "Cannot verify database compatibility. Check read access to the "
            "required Web-Tools tables, then retry.") from None
    missing = []
    for table in tables:
        if table not in existing:
            missing.append(table + " (table)")
        else:
            missing.extend(table + "." + column for column in sorted(
                REQUIRED_COLUMNS[table] - existing[table]))
    if missing:
        raise SchemaCompatibilityError(
            "Database schema is incompatible with SecondChecking contract 2. "
            "Ask the Web-Tools administrator to back up and apply migrations "
            "through " + MINIMUM_SERVER_MIGRATION + " (or a later head), then retry. "
            "Missing: " + ", ".join(missing))
