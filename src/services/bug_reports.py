"""Explicit, retryable upload of a frozen, allowlisted diagnostic envelope."""
import json
import platform
import uuid

from services.diagnostic_schema import envelope, MAX_BYTES
from services import runtime, transport, operator_session
from services.configuration import service_settings
from services.report_attachments import collect_attachments, report_category


def prepare_report(incident=None):
    from services.build_identity import read_identity
    from version import __version__
    try:
        build = read_identity() or {}
    except (OSError, ValueError, KeyError):
        build = {}
    incident = incident or runtime.diagnostic_record('support.manual_report')
    events = runtime.recent_diagnostics()
    if report_category(incident, events) == 'sysprep':
        # Windows may finish writing Panther after the original app error.
        # Re-read the bounded code-only summary when the report is opened.
        from services.maintenance import collect_sysprep_diagnostics
        collect_sysprep_diagnostics()
        events = runtime.recent_diagnostics()
    attachments, notes = collect_attachments(incident, events)
    report = envelope({
        'schema_version': 1, 'report_id': uuid.uuid4().hex,
        'incident': incident,
        'events': events, 'attachments': attachments, 'attachment_notes': notes,
        'build': {'version': __version__, 'commit': build.get('commit', 'source'),
                  'build_id': build.get('build_id', 'source'),
                  'python': platform.python_version(),
                  'windows': platform.version()}})
    while len(json.dumps(report).encode('utf-8')) > MAX_BYTES:
        if len(report['events']) > 5:
            report['events'].pop(0)
        elif report['attachments'] and any(item['size'] for item in report['attachments']):
            largest = max(report['attachments'], key=lambda item: item['size'])
            data = largest['text'].encode('utf-8')
            remaining = len(data) // 2
            largest.update(text=data[-remaining:].decode('utf-8', errors='ignore') if remaining else '',
                           truncated=True)
            report = envelope(report)
        elif report['events']:
            report['events'].pop(0)
        else:
            raise RuntimeError('The diagnostic report exceeds the upload limit.')
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
    if report.get('attachments'):
        try:
            capability = transport.get(base + '/api/second-check/bug-reports/capabilities',
                                       headers=headers, timeout=10)
            supported = capability.json()
        except (transport.requests.RequestException, ValueError):
            raise RuntimeError('Could not verify attachment support. Check the connection and retry.') from None
        if (capability.status_code != 200 or not isinstance(supported, dict)
                or supported.get('attachments_version') != 1):
            raise RuntimeError('Update Web-Tools to support attached diagnostic files. Nothing was uploaded.')
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
    if report.get('attachments') and (type(body.get('attachment_count')) is not int
            or body['attachment_count'] != len(report['attachments'])):
        raise RuntimeError('Web-Tools did not confirm the attached files. Update its reporting service, then retry this report.')
    return report['report_id']
