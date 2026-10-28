"""Readable saved evidence; unknown fields remain explicitly unknown."""

from services.check_results import TEST_KEYS, badge_text


def value(data):
    if data is None or data == '' or data == {} or data == []:
        return 'Not recorded'
    if isinstance(data, dict):
        return '\n'.join('{}: {}'.format(str(key).replace('_', ' '),
                         value(item).replace('\n', '\n  '))
                         for key, item in data.items())
    if isinstance(data, list):
        return '\n'.join('- ' + value(item).replace('\n', '\n  ')
                         for item in data)
    return str(data)


def format_saved_report(saved, order_number, serial_number):
    if not isinstance(saved, dict) or saved.get('success') is not True:
        raise ValueError('The service did not confirm this report.')
    if saved.get('found') is False:
        return ('No current assignment/report was found for order {} and serial {}.\n'
                'The assignment may have changed. Refresh the serial list; '
                'no saved tests have been inferred.').format(order_number, serial_number)
    if saved.get('found') is not True:
        raise ValueError('The service did not confirm whether a report exists.')
    if saved.get('saved_report_version') != 1:
        raise ValueError('Upgrade the matching Web-Tools service to view the complete saved report.')
    if (saved.get('serial_number') != serial_number
            or str(saved.get('lookup_reference', saved.get('order_number'))) != str(order_number)):
        raise ValueError('The returned report belongs to a different order or exact serial.')
    tests, overrides = saved.get('test_results'), saved.get('test_overrides', {})
    if not isinstance(tests, dict) or not isinstance(overrides, dict):
        raise ValueError('Invalid saved test results.')
    if saved.get('data_state') not in ('saved_report', 'legacy_serial_only'):
        raise ValueError('Invalid saved report state.')
    state = dict(tests, _overrides=overrides,
                 _history_unknown=saved.get('history_unknown', list(TEST_KEYS)
                                           if not saved.get('provenance_known') else []))
    lines = ['SAVED ORDER REPORT',
             'Source: authenticated Web-Tools saved data (not live device measurements)',
             'Order: {} (ID {}; lookup {})'.format(value(saved.get('order_number')),
                                                   value(saved.get('order_id')), order_number),
             'Serial: ' + serial_number, 'SKU: ' + value(saved.get('sku')),
             'Report ID: ' + value(saved.get('report_id')),
             'Checked by: ' + value(saved.get('checked_by')),
             'Checked at (as recorded): ' + value(saved.get('checked_at'))]
    if saved.get('data_state') == 'legacy_serial_only':
        lines.append('LEGACY DATA ONLY: no full check report, receipt or capture time is available. '
                     'Override/coverage history is unknown.')
    lines += ['', 'CURRENT ASSIGNMENT (WHEN LOADED)', value(saved.get('assignment')),
              '', 'COMMITTED RECEIPT FOR THIS REPORT', value(saved.get('receipt')),
              'A historical receipt does not establish the device’s current assignment.',
              '', 'SAVED CHECKS']
    for key in TEST_KEYS:
        lines.append('{}: {}'.format(key.title(), badge_text(state, key)))
    lines += ['', 'OVERRIDE HISTORY']
    if not overrides:
        lines.append('None recorded' if saved.get('provenance_known') else 'Unknown / not recorded')
    for key, events in overrides.items():
        for event in events:
            lines.append('{} — {}: measured {}; previous {}; decision {}; by {}; at {}; reason: {}'.format(
                key.title(), 'ACTIVE' if event.get('active') else 'SUPERSEDED',
                value(event.get('measured_result')), value(event.get('previous_result')),
                value(event.get('result')), value(event.get('operator')),
                value(event.get('at')), value(event.get('reason'))))
    for title, data in (
        ('SPECIFICATIONS (SAVED SNAPSHOT)', saved.get('specs')),
        ('MEASUREMENT SOURCE / CAPTURE TIME', saved.get('device_measurements')),
        ('TEST COVERAGE (AS RECORDED)', saved.get('test_coverage')),
        ('STORAGE INVENTORY', saved.get('storage_inventory')),
        ('STORAGE CONFIGURATION REVIEW', saved.get('storage_review')),
        ('BATTERY EVIDENCE', saved.get('battery_evidence')),
        ('BATTERY EXPORT METADATA (FILE BODY OMITTED)', saved.get('battery_capture')),
        ('LOCAL MDM EVIDENCE — TENANT STATUS NOT VERIFIED', saved.get('mdm_evidence')),
        ('ASSIGNMENT REVIEW / EXCEPTION REASON', saved.get('assignment_review')),
    ):
        lines += ['', title, value(data)]
    lines.append('\nMissing source/time/coverage is not evidence that a check passed. '
                 'Naive timestamps have no recorded offset; no timezone is inferred.')
    return '\n'.join(lines)
