"""Fixed diagnostic sources only; never accept an operator-supplied file path."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import re
from uuid import UUID
from itertools import islice

from services import runtime
from services.diagnostic_schema import (MAX_ATTACHMENT_BYTES, attachment_record,
                                        attachment_text, event_record)


def report_category(incident, events):
    target = incident or {}
    name = target.get('event', '')
    if name in ('ui.error', 'support.manual_report', ''):
        eligible = [event for event in events if (event.get('level') == 'ERROR'
                    or event.get('context', {}).get('exit_code') not in (None, 0))
                    and event.get('event') != 'ui.error'
                    and not event.get('event', '').startswith('support.')
                    and (not target.get('at') or event.get('at', '') <= target['at'])]
        target = eligible[-1] if eligible else {}
        name = target.get('event', '')
    kind = target.get('context', {}).get('kind')
    helper = name.startswith(('maintenance.', 'helper.'))
    if name.startswith('sysprep.') or (helper and kind == 'sysprep'):
        return 'sysprep'
    if name.startswith('windows_update.') or (helper and kind == 'windows-update'):
        return 'windows-update'
    if name.startswith('update.') or (name.startswith('helper.') and kind == 'updates'):
        return 'app-update'
    return 'app'


def _file_tail(path):
    if path.is_symlink():
        raise OSError('Unsupported diagnostic source')
    with path.open('rb') as stream:
        marker = stream.read(2)
        size = stream.seek(0, 2)
        start = max(0, size - 128 * 1024)
        if marker in (b'\xff\xfe', b'\xfe\xff'):
            start -= start % 2
        stream.seek(start)
        data = stream.read(128 * 1024)
    encoding = ('utf-16-le' if marker == b'\xff\xfe' else
                'utf-16-be' if marker == b'\xfe\xff' else 'utf-8-sig')
    text = data.decode(encoding, errors='replace').lstrip('\ufeff')
    if start:
        text = text.split('\n', 1)[-1] if '\n' in text else ''
    modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    return text, start > 0, modified


def _windows_update_events():
    from services.maintenance import _powershell_executable
    script = r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
try {
    @(Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-WindowsUpdateClient/Operational';StartTime=(Get-Date).AddMinutes(-30)} -MaxEvents 30 |
      ForEach-Object { @{time=$_.TimeCreated.ToUniversalTime().ToString('o');id=$_.Id;level=$_.Level;message=([string]$_.Message).Substring(0,[Math]::Min(4096,([string]$_.Message).Length))} }) | ConvertTo-Json -Depth 4 -Compress
} catch { exit 3 }
'''
    result = subprocess.run([str(_powershell_executable()), '-NoProfile', '-NonInteractive',
        '-Command', script], capture_output=True, encoding='utf-8', errors='replace',
        timeout=8, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode != 0:
        raise OSError('Windows Update evidence unavailable')
    try:
        records = json.loads(result.stdout.strip() or '[]')
    except ValueError:
        raise OSError('Windows Update evidence could not be read') from None
    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list):
        raise OSError('Windows Update evidence could not be read')
    return '\n\n'.join('[{}] Event {} (level {})\n{}'.format(
        item.get('time', ''), item.get('id', ''), item.get('level', ''), item.get('message', ''))
        for item in records[:30] if isinstance(item, dict))


def collect_attachments(incident, events):
    attachments, notes = [], []
    private = runtime.diagnostic_private_values()

    def add(name, text, truncated=False, modified=None):
        data = attachment_text(text, private).encode('utf-8')
        if len(data) > MAX_ATTACHMENT_BYTES:
            data = data[-MAX_ATTACHMENT_BYTES:]
            truncated = True
        item = {'name': name, 'text': data.decode('utf-8', errors='ignore'),
                'truncated': truncated, 'modified_at': modified}
        attachments.append(attachment_record(item))

    def read(name, path):
        try:
            text, truncated, modified = _file_tail(path)
            add(name, text, truncated, modified)
        except FileNotFoundError:
            notes.append({'name': name, 'reason': 'missing'})
        except OSError:
            notes.append({'name': name, 'reason': 'unavailable'})

    safe_events = [event_record(event) for event in events]
    if incident:
        safe_events.append(event_record(incident))
    add('app-diagnostics.jsonl', '\n'.join(json.dumps(event) for event in safe_events))
    category = report_category(incident, events)
    if category == 'sysprep':
        import win32api
        root = Path(win32api.GetSystemDirectory()) / 'Sysprep' / 'Panther'
        read('sysprep-setuperr.log', root / 'setuperr.log')
        read('sysprep-setupact.log', root / 'setupact.log')
    elif category == 'windows-update':
        try:
            add('windows-update-events.log', _windows_update_events())
        except (OSError, subprocess.SubprocessError):
            notes.append({'name': 'windows-update-events.log', 'reason': 'unavailable'})
    elif category == 'app-update':
        root = runtime.app_directory() / '.secondchecking-updates'
        try:
            states = []
            for folder in sorted(islice(root.iterdir(), 100), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
                try:
                    if str(UUID(folder.name)) != folder.name:
                        continue
                except ValueError:
                    continue
                path = folder / 'state.json'
                if folder.is_symlink() or path.is_symlink() or path.stat().st_size > 65536:
                    continue
                value = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(value, dict):
                    continue
                state = {}
                if value.get('state') in ('downloading', 'prepared', 'blocked', 'installing',
                        'restarting', 'installed', 'failed_retained', 'rolled_back',
                        'recovery_required', 'rollback_restart_failed'):
                    state['state'] = value['state']
                if value.get('reason') in ('requested_recovery', 'replacement_or_restart_failed',
                        'installed_copy_retained', 'retained_backup_needs_recovery',
                        'installed_file_changed', 'open_previous_version_manually',
                        'worker_validation_or_handoff_failed'):
                    state['reason'] = value['reason']
                for key in ('version', 'from_version'):
                    if isinstance(value.get(key), str) and re.fullmatch(r'\d{1,5}\.\d{1,5}\.\d{1,5}', value[key]):
                        state[key] = value[key]
                states.append(state)
            add('app-update-state.json', json.dumps(states, indent=2))
        except (OSError, ValueError, TypeError):
            notes.append({'name': 'app-update-state.json', 'reason': 'unavailable'})
    return attachments, notes
