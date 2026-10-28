"""Configuration shared by source, packaged and headless entry points."""
import configparser
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    """A safe message containing field names, never supplied values."""


def application_directory():
    """Stable deployment root, independent of the launch working directory."""
    return (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2])


def config_path():
    if "SECOND_CHECK_CONFIG" in os.environ:
        return Path(os.environ["SECOND_CHECK_CONFIG"])
    return application_directory() / "config.ini"


def read_config(path=None):
    config = configparser.ConfigParser(interpolation=None)
    target = Path(path) if path is not None else config_path()
    explicit = path is not None or "SECOND_CHECK_CONFIG" in os.environ
    try:
        with target.open(encoding="utf-8-sig") as stream:
            config.read_file(stream)
    except FileNotFoundError:
        if explicit:
            raise ConfigurationError("Cannot read SECOND_CHECK_CONFIG file.") from None
    except (OSError, UnicodeError, configparser.Error):
        raise ConfigurationError("Cannot read config.ini; check access and INI syntax.") from None
    from services.runtime import register_private_values
    register_private_values(config.get(section, option, raw=True)
                            for section in config.sections()
                            for option in config.options(section)
                            if section in ('database', 'webtools')
                            and option not in ('ssl_ca',))
    return config


def setting(config, section, option, env):
    # Presence wins, including an empty value: never silently reuse old credentials.
    return os.environ[env] if env in os.environ else config.get(
        section, option, fallback="", raw=True)


def database_settings(config):
    fields = {"host": "DB_HOST", "user": "DB_USER",
              "password": "DB_PASSWORD", "database": "DB_NAME"}
    settings = {key: setting(config, "database", key, env)
                for key, env in fields.items()}
    invalid = [env for key, env in fields.items()
               if not settings[key].strip() or any(
                   char in settings[key] for char in ("\x00", "\r", "\n"))
               or settings[key].strip().lower() in ("<secret>", "<required>")]
    if (any(char.isspace() for char in settings["host"])
            or "://" in settings["host"]):
        if "DB_HOST" not in invalid:
            invalid.append("DB_HOST")
    if invalid:
        raise ConfigurationError("Set missing or invalid fields: " + ", ".join(invalid))
    return settings


def webtools_settings(config, required=True):
    url = setting(config, "webtools", "base_url", "SECOND_CHECK_BASE_URL").strip()
    key = setting(config, "webtools", "second_check_key", "SECOND_CHECK_KEY").strip()
    invalid = []
    try:
        parsed = urlsplit(url)
        valid_url = (parsed.scheme in ("http", "https") and parsed.hostname
                     and not parsed.username and not parsed.password
                     and not parsed.query and not parsed.fragment
                     and not any(c.isspace() for c in url))
        parsed.port  # Reject invalid ports without echoing their value.
    except ValueError:
        valid_url = False
    if not valid_url:
        invalid.append("SECOND_CHECK_BASE_URL")
    else:
        from services.transport import TransportError, validate_url
        try:
            validate_url(url)
        except TransportError:
            invalid.append("SECOND_CHECK_BASE_URL (HTTPS required)")
    if not key or key.lower() in ("<secret>", "<required>") or any(
            c in key for c in ("\r", "\n", "\x00")):
        invalid.append("SECOND_CHECK_KEY")
    if required and invalid:
        raise ConfigurationError("Set missing or invalid fields: " + ", ".join(invalid))
    return url.rstrip("/"), key


def validate_configuration():
    config = read_config()
    database_tls_options(database_settings(config)["host"], config)
    webtools_settings(config)
    return config


def database_tls_options(host, config=None):
    """Require certificate/hostname verification; local plaintext is opt-in."""
    from services.transport import loopback
    if os.environ.get("DB_ALLOW_INSECURE_LOOPBACK") == "1":
        if not loopback(host):
            raise ConfigurationError("DB_ALLOW_INSECURE_LOOPBACK requires a literal loopback DB_HOST.")
        return {"ssl_mode": "DISABLED", "local_infile": False}
    config = config if config is not None else read_config()
    ca = setting(config, "database", "ssl_ca", "DB_SSL_CA").strip()
    options = {"ssl_mode": "VERIFY_IDENTITY", "local_infile": False}
    if ca:
        path = Path(ca)
        if not path.is_absolute():
            path = application_directory() / path
        try:
            path = path.resolve(strict=True)
            if not path.is_file():
                raise OSError('Not a file')
        except (OSError, RuntimeError, ValueError):
            raise ConfigurationError(
                "Set DB_SSL_CA to a readable CA certificate path; relative paths "
                "are resolved beside the executable.") from None
        options["ssl"] = {"ca": str(path)}
    return options


def service_settings():
    """Resolve required API configuration without importing hardware or GUI."""
    try:
        return webtools_settings(read_config())
    except ConfigurationError:
        raise RuntimeError(
            "Configure SECOND_CHECK_BASE_URL and SECOND_CHECK_KEY, then Retry.") from None
