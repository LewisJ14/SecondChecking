"""Version-one support envelope with bounded, redacted diagnostic attachments.

This contract is also enforced by the receiving Astro service.
"""
from datetime import datetime
import hashlib
import ipaddress
import math
import re

MAX_EVENTS = 60
MAX_BYTES = 192 * 1024
MAX_ATTACHMENT_BYTES = 48 * 1024
ATTACHMENT_NAMES = frozenset({
    'app-diagnostics.jsonl', 'sysprep-setuperr.log', 'sysprep-setupact.log',
    'windows-update-events.log', 'app-update-state.json'})
TOKEN = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]{0,79}\Z')
HEX = re.compile(r'[0-9a-f-]{7,64}\Z')
FRAME = re.compile(r'[A-Za-z0-9_]+\.py:[0-9]{1,7}:[A-Za-z0-9_<>]+\Z')
CONTEXT = {'stage', 'kind', 'state', 'result', 'reason', 'frames_seen',
           'camera_index', 'attempt', 'timeout_seconds', 'elapsed_ms',
           'count', 'source_rate', 'sample_rate', 'channels', 'exit_code',
           'http_status', 'native_code', 'line_number'}


def attachment_text(value, private_values=()):
    """Keep diagnostic sentences/codes; remove credentials and identifiers."""
    for private in sorted(set(str(v) for v in private_values if v and len(str(v)) >= 4),
                          key=len, reverse=True):
        value = value.replace(private, '[private]')
    value = re.sub(r'https?://[^\s\"\'<>]+', '[url]', value, flags=re.I)
    value = re.sub(r'\b(?:Bearer|Basic)\s+[A-Za-z0-9+/=._~-]+', '[authorization]', value, flags=re.I)
    value = re.sub(r'''(?ix)(["']?(?:password|passwd|pwd|api[_-]?key|second_check_key|token|access_token|refresh_token|authorization|cookie|secret)["']?\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;}]+)''', r'\1[private]', value)
    value = re.sub(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', '[email]', value, flags=re.I)
    value = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '[address]', value)
    def ipv6(match):
        try:
            ipaddress.IPv6Address(match.group(0).split('%')[0])
            return '[address]'
        except ValueError:
            return match.group(0)
    value = re.sub(r'(?i)(?<![\w:])(?:[0-9a-f]{0,4}:){2,}[0-9a-f]{0,4}(?:%\w+)?', ipv6, value)
    value = re.sub(r'(?i)\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b', '[identifier]', value)
    value = re.sub(r'\bS-1-\d+(?:-\d+)+\b', '[account-id]', value, flags=re.I)
    value = re.sub(r'\b(?:[A-Z0-9]{5}-){4}[A-Z0-9]{5}\b', '[product-key]', value, flags=re.I)
    value = re.sub(r'-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----.*?-----END (?:[A-Z ]*PRIVATE KEY)-----', '[private-key]', value, flags=re.S)
    value = re.sub(r'(?i)\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b', '[hardware-address]', value)
    value = re.sub(r'''(?ix)(\b(?:serial(?:[\s_]?number)?|username|computername|computer|customer|order(?:[\s_]?number)?|device(?:id|_id)?|tenant(?:id|_id)?)\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\r\n,;|]+)''', r'\1[identifier]', value)
    value = re.sub(r'''(?i)(\bfor user\s+)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\r\n,;]+)''', r'\1[operator]', value)
    value = re.sub(r'''(?i)["'](?:[A-Z]:\\|\\\\)[^\r\n"']*["']''', '[path]', value)
    value = re.sub(r'(?i)(?:\b[A-Z]:\\|\\\\)[^\r\n]*', '[path]', value)
    value = re.sub(r'/(?:Users|home)/[^\s\r\n]+', '[user-path]', value)
    value = re.sub(r'(?i)\b(?:USB|PCI|ACPI|HID|SWD|BTHENUM)\\[^\s,;]+', '[device-id]', value)
    value = re.sub(r'(?<![\w])[A-Za-z0-9_+/=-]{40,}(?![\w])', '[opaque-value]', value)
    value = re.sub(r'\b\d{6}(?:-\d{6}){7}\b', '[recovery-key]', value)
    return ''.join(c for c in value if c in '\n\r\t' or ord(c) >= 32)


def attachment_record(value):
    if (not isinstance(value, dict) or not isinstance(value.get('name'), str)
            or value['name'] not in ATTACHMENT_NAMES):
        raise ValueError('Unsupported diagnostic attachment')
    text = value.get('text')
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_ATTACHMENT_BYTES:
        raise ValueError('Invalid diagnostic attachment size')
    text = attachment_text(text)
    data = text.encode('utf-8')
    truncated = value.get('truncated') is True or len(data) > MAX_ATTACHMENT_BYTES
    if len(data) > MAX_ATTACHMENT_BYTES:
        text = data[-MAX_ATTACHMENT_BYTES:].decode('utf-8', errors='ignore')
        data = text.encode('utf-8')
    result = {'name': value['name'], 'text': text, 'size': len(data),
              'sha256': hashlib.sha256(data).hexdigest(),
              'redacted': True, 'truncated': truncated}
    if timestamp(value.get('modified_at')):
        result['modified_at'] = value['modified_at']
    return result


def token(value, fallback='unknown'):
    return value if isinstance(value, str) and TOKEN.fullmatch(value) else fallback


def timestamp(value):
    try:
        return (isinstance(value, str) and len(value) <= 40
                and datetime.fromisoformat(value.replace('Z', '+00:00')).utcoffset()
                is not None)
    except ValueError:
        return False


def event_record(value):
    if not isinstance(value, dict) or not timestamp(value.get('at')):
        raise ValueError('Invalid diagnostic event')
    result = {'at': value['at'], 'event': token(value.get('event')),
              'level': value.get('level') if value.get('level') in
              ('INFO', 'WARNING', 'ERROR') else 'INFO',
              'run': value.get('run') if isinstance(value.get('run'), str)
              and HEX.fullmatch(value['run']) else 'unknown'}
    context = value.get('context', {})
    result['context'] = {}
    if isinstance(context, dict):
        for key in CONTEXT:
            item = context.get(key)
            if type(item) in (int, float) and abs(item) < 1e15 and math.isfinite(item):
                result['context'][key] = item
            elif isinstance(item, bool):
                result['context'][key] = item
            elif isinstance(item, str) and TOKEN.fullmatch(item):
                result['context'][key] = item
    result['exceptions'] = []
    exceptions = value.get('exceptions', [])
    for error in exceptions[:5] if isinstance(exceptions, list) else []:
        if not isinstance(error, dict):
            continue
        frames = error.get('frames', [])
        clean = {'type': token(error.get('type')), 'frames': [
            frame for frame in frames[-10:] if isinstance(frame, str)
            and FRAME.fullmatch(frame)] if isinstance(frames, list) else []}
        for key in ('error_code', 'errno', 'winerror', 'hresult', 'code'):
            if type(error.get(key)) is int and abs(error[key]) < 1e15:
                clean[key] = error[key]
        codes = error.get('numeric_codes', [])
        if isinstance(codes, list):
            clean['numeric_codes'] = [code for code in codes[:8]
                                     if type(code) is int and abs(code) < 1e15]
        result['exceptions'].append(clean)
    return result


def envelope(value):
    if not isinstance(value, dict) or value.get('schema_version') != 1:
        raise ValueError('Unsupported bug report format')
    report_id = value.get('report_id')
    if not isinstance(report_id, str) or not re.fullmatch(r'[0-9a-f]{32}', report_id):
        raise ValueError('Invalid report reference')
    events = value.get('events')
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ValueError('Too many diagnostic events')
    build = value.get('build', {})
    if not isinstance(build, dict):
        raise ValueError('Invalid build identity')
    result = {'schema_version': 1, 'report_id': report_id,
            'incident': event_record(value.get('incident')),
            'events': [event_record(event) for event in events],
            'build': {key: item for key, item in build.items()
                      if key in ('version', 'commit', 'build_id', 'python', 'windows')
                      and isinstance(item, str) and len(item) <= 64
                      and re.fullmatch(r'[A-Za-z0-9_.-]+', item)}}
    if 'attachments' in value:
        attachments = value['attachments']
        if not isinstance(attachments, list) or len(attachments) > len(ATTACHMENT_NAMES):
            raise ValueError('Invalid diagnostic attachments')
        result['attachments'] = [attachment_record(item) for item in attachments]
        if len({item['name'] for item in result['attachments']}) != len(attachments):
            raise ValueError('Duplicate diagnostic attachment')
    if 'attachment_notes' in value:
        notes = value['attachment_notes']
        if not isinstance(notes, list) or len(notes) > len(ATTACHMENT_NAMES):
            raise ValueError('Invalid attachment notes')
        result['attachment_notes'] = [
            {'name': item['name'], 'reason': item['reason']} for item in notes
            if isinstance(item, dict) and item.get('name') in ATTACHMENT_NAMES
            and item.get('reason') in ('missing', 'unavailable', 'size_limit')]
    return result
