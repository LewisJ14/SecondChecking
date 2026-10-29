"""Verified service transport; credentials never follow redirects."""
import ipaddress
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit
import requests


class TransportError(requests.RequestException):
    pass


def loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_url(value):
    try:
        parsed = urlsplit(value)
        parsed.port
        secure = parsed.scheme == 'https'
        local_test = (parsed.scheme == 'http' and loopback(parsed.hostname or '')
                      and os.environ.get('SECOND_CHECK_ALLOW_HTTP_LOOPBACK') == '1')
        valid = (secure or local_test) and parsed.hostname and not (
            parsed.username or parsed.password or parsed.query or parsed.fragment
            or '\\' in value or any(c.isspace() for c in value)
            or any(p in {'.', '..'} for p in unquote(parsed.path).split('/')))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise TransportError('Service requires HTTPS with a valid certificate. '
                             'Plain HTTP is restricted to explicitly enabled loopback tests.')
    return value.rstrip('/')


def verification():
    value = os.environ.get('SECOND_CHECK_CA_BUNDLE')
    if value is None:
        return True
    path = Path(value)
    if not value or not path.is_absolute() or not path.is_file():
        raise TransportError('Set SECOND_CHECK_CA_BUNDLE to a readable absolute CA bundle path.')
    return str(path)


def _call(sender, url, *args, **kwargs):
    validate_url(url)
    # Callers cannot turn verification off or forward credentials to a redirect.
    kwargs['verify'] = verification()
    kwargs['allow_redirects'] = False
    kwargs.setdefault('timeout', 15)
    try:
        response = sender(url, *args, **kwargs)
    except requests.RequestException as error:
        from services.runtime import log_diagnostic
        log_diagnostic('service.connection_failed', error=error, stage='transport')
        raise TransportError('Service connection failed; verify TLS, configuration and connectivity.') from None
    if response.status_code >= 400:
        from services.runtime import log_diagnostic
        log_diagnostic('service.http_error', stage='transport', http_status=response.status_code)
    if 300 <= response.status_code < 400:
        raise TransportError('Service redirect refused. Configure the final HTTPS service address.')
    return response


def get(url, **kwargs):
    return _call(requests.get, url, **kwargs)


def post(url, **kwargs):
    return _call(requests.post, url, **kwargs)


def request(method, url, **kwargs):
    return _call(lambda address, **options: requests.request(method, address, **options), url, **kwargs)
