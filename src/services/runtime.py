"""Runtime paths and logging, independent of GUI, database and hardware code."""
from datetime import datetime, timedelta, timezone
from collections import deque
from pathlib import Path
import json
import os
import re
import sys
import threading
import traceback
from uuid import uuid4

_RUN_ID = uuid4().hex[:12]
_LOCK = threading.RLock()
_SECRETS = set()
_DIAGNOSTICS = deque(maxlen=60)


def register_private_values(values):
    """Register configuration values without persisting them anywhere."""
    with _LOCK:
        _SECRETS.update(str(value) for value in values if value and len(str(value)) >= 4)


def redact_text(message):
    """Defence in depth for older text events; diagnostics use an allowlist."""
    text = str(message)[:16000]
    private = set(_SECRETS)
    private.update(value for key, value in os.environ.items()
                   if re.search(r'PASSWORD|SECRET|TOKEN|API_KEY|SECOND_CHECK_KEY', key, re.I)
                   and len(value) >= 4)
    for value in sorted(private, key=len, reverse=True):
        text = text.replace(value, '[private]')
    text = re.sub(r'https?://[^\s\"\'<>]+', '[url]', text, flags=re.I)
    text = re.sub(r'\b(?:Bearer|Basic)\s+[A-Za-z0-9+/=._~-]+', '[authorization]', text, flags=re.I)
    text = re.sub(r'''(?ix)(["']?(?:password|passwd|pwd|api[_-]?key|second_check_key|token|access_token|refresh_token|authorization|cookie|secret)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}]+)''', r'\1[private]', text)
    text = re.sub(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', '[email]', text, flags=re.I)
    text = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '[address]', text)
    text = re.sub(r'(?i)\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b', '[identifier]', text)
    text = re.sub(r'''(?ix)(\b(?:serial(?:[\s_]number)?|username|assigned_by|device|tenant(?:id|_id)?|preferredserial)\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;|]+)''', r'\1[identifier]', text)
    text = re.sub(r'(?i)\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b', '[hardware-address]', text)
    text = re.sub(r'''(?i)(\b(?:serial_id|file)\s*=\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)''', r'\1[identifier]', text)
    text = re.sub(r'''(?i)(\bserial\s+)["'][^"']*["']''', r'\1[identifier]', text)
    text = re.sub(r'(?i)(Login (?:failed|succeeded) for )[^:]+', r'\1[operator]', text)
    # Subprocess commands, arbitrary response bodies and SQL are not support data.
    text = re.sub(r'(?is)(?:Command\s+\[|payload\s*=|response\s*=|\bSELECT\s+|\bINSERT\s+|\bUPDATE\s+\w+\s+SET\s+).*', '[private operation details omitted]', text)
    text = re.sub(r'''(?i)(?:[A-Z]:\\|\\\\)[^\r\n"']+''', '[path]', text)
    text = re.sub(r'/Users/[^\s/]+|/home/[^\s/]+', '[user-path]', text)
    return ''.join(char if char >= ' ' else ('\\n' if char == '\n' else ' ')
                   for char in text)


def exception_report(error):
    """Keep types, codes and code locations; never exception arguments/locals."""
    report = []
    seen = set()
    while error is not None and id(error) not in seen and len(report) < 5:
        seen.add(id(error))
        item = {'type': type(error).__name__, 'frames': [
            '{}:{}:{}'.format(Path(frame.filename).name, frame.lineno, frame.name)
            for frame in traceback.extract_tb(error.__traceback__)[-10:]]}
        if error.args and type(error.args[0]) is int:
            item['error_code'] = error.args[0]
        numeric_args = [value for value in error.args if type(value) is int]
        if numeric_args:
            item['numeric_codes'] = numeric_args[:8]
        for name in ('errno', 'winerror', 'hresult', 'code'):
            value = getattr(error, name, None)
            if type(value) is int:
                item[name] = value
        report.append(item)
        error = error.__cause__ or error.__context__
    return report


def log_diagnostic(event, error=None, **context):
    """Structured support fields are deliberately limited to operational data."""
    allowed = {'stage', 'kind', 'state', 'result', 'reason', 'frames_seen',
               'camera_index', 'attempt', 'timeout_seconds', 'elapsed_ms',
               'version', 'build', 'count', 'request_id'}
    allowed.update({'source_rate', 'sample_rate', 'channels'})
    allowed.update({'exit_code', 'http_status', 'native_code', 'line_number'})
    data = {key: value for key, value in context.items()
            if key in allowed and isinstance(value, (str, int, float, bool, type(None)))}
    if error is not None:
        data['exceptions'] = exception_report(error)
    failed = (error is not None or event.endswith(('.failed', '_failed', '.error'))
              or data.get('result') == 'error')
    level = ('ERROR' if failed else 'WARNING'
             if data.get('result') in ('fail', 'unavailable') else 'INFO')
    record = diagnostic_record(event, data, level)
    _write_diagnostic(record)
    log_event('{} {}'.format(event, json.dumps(data, ensure_ascii=True)),
              level=level)
    return record


def diagnostic_record(event, data=None, level='ERROR'):
    from services.diagnostic_schema import event_record
    data = data or {}
    # Values registered as private cannot become token-shaped context either.
    context = {key: redact_text(value) if isinstance(value, str) else value
               for key, value in data.items() if key != 'exceptions'}
    return event_record({'at': datetime.now(timezone.utc).isoformat(),
                         'event': redact_text(event), 'run': _RUN_ID,
                         'level': level, 'context': context,
                         'exceptions': data.get('exceptions', [])})


def diagnostic_path():
    return log_path().with_name('diagnostics.jsonl')


def _write_diagnostic(record):
    with _LOCK:
        _DIAGNOSTICS.append(record)
        try:
            path = diagnostic_path()
            if path.exists() and path.stat().st_size > 1024 * 1024:
                previous = path.with_suffix('.jsonl.1')
                if previous.exists():
                    previous.unlink()
                path.replace(previous)
            with path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record, ensure_ascii=True) + '\n')
        except OSError:
            pass


def recent_diagnostics():
    """Bounded 30-minute evidence, including worker processes; no raw logs."""
    from services.diagnostic_schema import event_record
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    records = list(_DIAGNOSTICS)
    for path in (diagnostic_path().with_suffix('.jsonl.1'), diagnostic_path()):
        try:
            with path.open('rb') as stream:
                size = stream.seek(0, 2)
                stream.seek(max(0, size - 256 * 1024))
                lines = stream.read(256 * 1024).decode('utf-8', errors='replace').splitlines()
            for line in lines:
                try:
                    records.append(event_record(json.loads(line)))
                except (ValueError, TypeError):
                    continue
        except OSError:
            pass
    unique = {}
    for record in records:
        try:
            if datetime.fromisoformat(record['at'].replace('Z', '+00:00')) >= cutoff:
                unique[json.dumps(record, sort_keys=True)] = record
        except (ValueError, KeyError, TypeError):
            continue
    return sorted(unique.values(), key=lambda record: record['at'])[-60:]


def app_directory():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def log_path():
    return app_directory() / "logs.txt"


def log_event(message, level=None):
    text = redact_text(message)
    if level is None:
        level = ('ERROR' if re.search(r'\berror\b|exception|failed|timed out', text, re.I)
                 else 'WARNING' if re.search(r'warning|unavailable|mismatch|not confirmed', text, re.I)
                 else 'INFO')
    path = log_path()
    try:
        with _LOCK:
            if path.exists() and path.stat().st_size > 5 * 1024 * 1024:
                previous = path.with_name(path.name + ".1")
                if previous.exists():
                    previous.unlink()
                path.rename(previous)
            with path.open("a", encoding="utf-8") as stream:
                stream.write("[{}] [{}] run={} pid={} thread={} {}\n".format(
                    datetime.now().astimezone().isoformat(timespec='milliseconds'),
                    level, _RUN_ID, os.getpid(), threading.get_ident(), text))
    except OSError:
        # Logging failure must not break a windowed client with no stdout.
        pass
