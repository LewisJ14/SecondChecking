"""Describe observed coverage without claiming unmeasured hardware quality."""

from copy import deepcopy
from datetime import datetime, timezone


def record_coverage(results, key, scope, details):
    results.setdefault('_coverage', {})[key] = {
        'version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(),
        'scope': scope, 'details': deepcopy(details),
    }


def coverage_lines(results):
    lines = []
    for key, evidence in results.get('_coverage', {}).items():
        if not isinstance(evidence, dict) or not evidence.get('scope'):
            continue
        line = '{} coverage: {}'.format(key.title(), evidence['scope'])
        if key == 'webcam':
            line = 'Webcam coverage: Displayed camera image only.'
        elif key == 'wifi':
            line = 'Wi-Fi coverage: Adapter detection only.'
        elif key == 'usb':
            line = 'USB checks:'
        detail = evidence.get('details', {})
        if key == 'keyboard':
            line += ' Missing keys: {}. Manual check: {}'.format(
                ', '.join(detail.get('missing_keys', [])) or 'none',
                detail.get('manual_confirmation') or 'not recorded')
        if key == 'usb':
            if detail.get('port_count_declared') is False:
                description = ('Detected insertions' if detail.get('automatic_insertion_detection')
                               else 'Confirmed insertion checks')
                line += ' {}: {}. Every physical port checked: {}.'.format(
                    description,
                    len(detail.get('observed_ports', {})),
                    'operator confirmed' if detail.get('operator_confirmed_all_ports')
                    else 'not confirmed')
            else:
                line += ' Required ports: {}. Detected at: {}.'.format(
                    ', '.join(detail.get('required_ports', [])) or 'not set',
                    ', '.join(detail.get('observed_ports', {})) or 'none')
        lines.append(line)
    return lines
