"""Version-one support envelope: code evidence only, never arbitrary log text.

This contract is also enforced by the receiving Astro service.
"""
from datetime import datetime
import math
import re

MAX_EVENTS = 60
MAX_BYTES = 192 * 1024
TOKEN = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]{0,79}\Z')
HEX = re.compile(r'[0-9a-f-]{7,64}\Z')
FRAME = re.compile(r'[A-Za-z0-9_]+\.py:[0-9]{1,7}:[A-Za-z0-9_<>]+\Z')
CONTEXT = {'stage', 'kind', 'state', 'result', 'reason', 'frames_seen',
           'camera_index', 'attempt', 'timeout_seconds', 'elapsed_ms',
           'count', 'source_rate', 'sample_rate', 'channels', 'exit_code',
           'http_status', 'native_code', 'line_number'}


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
    return {'schema_version': 1, 'report_id': report_id,
            'incident': event_record(value.get('incident')),
            'events': [event_record(event) for event in events],
            'build': {key: item for key, item in build.items()
                      if key in ('version', 'commit', 'build_id', 'python', 'windows')
                      and isinstance(item, str) and len(item) <= 64
                      and re.fullmatch(r'[A-Za-z0-9_.-]+', item)}}
