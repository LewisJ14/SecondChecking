# SecondChecking

## Environment Variables

The application expects sensitive configuration to be provided via environment variables:

- `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` – MySQL connection settings.
- `WC_URL` – WooCommerce API base URL.
- `WC_CONSUMER_KEY` and `WC_CONSUMER_SECRET` – WooCommerce API credentials.
- `BATTERYINFOVIEW_SHA256` – expected SHA256 hash of the BatteryInfoView ZIP.

