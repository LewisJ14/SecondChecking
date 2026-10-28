"""Distinguish a confirmed no-update result from missing helper output."""

import json


def decode_update_result(output, current_version):
    if not output.strip():
        raise ValueError('Update helper returned no result; update status is unknown.')
    result = json.loads(output)
    if not isinstance(result, dict):
        raise ValueError('Invalid update helper response.')
    if result.get('update_check_version') == 1:
        if result.get('state') == 'up_to_date':
            if result.get('current_version') != current_version:
                raise ValueError('Update response does not match the running version.')
            return None
        if result.get('state') != 'update_available':
            raise ValueError('Update helper did not confirm a result.')
    elif 'update_check_version' in result or 'state' in result:
        raise ValueError('Unsupported update helper response.')
    # Older helpers can still announce an available manifest explicitly.
    if not isinstance(result.get('version'), str) or not result['version'].strip():
        raise ValueError('Update response has no release version.')
    return result
