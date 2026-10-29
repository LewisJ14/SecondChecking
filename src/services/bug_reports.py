"""Explicit, retryable upload of a frozen, allowlisted diagnostic envelope."""
import json
import platform
import uuid

from services.diagnostic_schema import envelope, MAX_BYTES
from services import runtime, transport, operator_session
from services.configuration import service_settings


def prepare_report(incident=None):
    from services.build_identity import read_identity
    from version import __version__
    try:
        build = read_identity() or {}
    except (OSError, ValueError, KeyError):
        build = {}
    events = runtime.recent_diagnostics()
    if any(event['event'].startswith('sysprep.') or
           (event['event'].startswith('maintenance.') and
            event['context'].get('kind') == 'sysprep') for event in events):
        # Windows may finish writing Panther after the original app error.
        # Re-read the bounded code-only summary when the report is opened.
        from services.maintenance import collect_sysprep_diagnostics
        collect_sysprep_diagnostics()
        events = runtime.recent_diagnostics()
    report = envelope({
        'schema_version': 1, 'report_id': uuid.uuid4().hex,
        'incident': incident or runtime.diagnostic_record('support.manual_report'),
        'events': events,
        'build': {'version': __version__, 'commit': build.get('commit', 'source'),
                  'build_id': build.get('build_id', 'source'),
                  'python': platform.python_version(),
                  'windows': platform.version()}})
    while len(json.dumps(report).encode('utf-8')) > MAX_BYTES and report['events']:
        report['events'].pop(0)
    return report


def upload_report(report):
    report = envelope(report)
    if len(json.dumps(report).encode('utf-8')) > MAX_BYTES:
        raise RuntimeError('The diagnostic report exceeds the upload limit.')
    base, key = service_settings()
    if not base or not key:
        raise RuntimeError('Bug reporting needs the Web-Tools connection configured.')
    headers = {'X-Second-Check-Key': key}
    headers.update(operator_session.headers(base))
    try:
        response = transport.post(base + '/api/second-check/bug-reports',
                                  headers=headers, json=report, timeout=20)
        body = response.json()
    except (transport.requests.RequestException, ValueError):
        raise RuntimeError('Could not upload the report. Check the connection and retry.') from None
    if response.status_code != 200 or not isinstance(body, dict) or body.get('success') is not True:
        messages = {401: 'The reporting service rejected this connection. Check the app configuration.',
                    404: 'Update Web-Tools to enable bug reports.',
                    429: 'Too many reports. Please wait before retrying.',
                    503: 'Bug reporting is not ready on Web-Tools. Ask an administrator to apply its migration.'}
        raise RuntimeError(messages.get(response.status_code,
                                       'The report was not accepted. Retry or contact an administrator.'))
    if body.get('report_id') != report['report_id']:
        raise RuntimeError('The reporting service returned an unexpected reference.')
    return report['report_id']
