"""Detect enabled WLAN interfaces; this does not test network quality."""

import ctypes
from ctypes import wintypes

from services.test_coverage import record_coverage
from utils.helpers import log_event


class InterfaceInfo(ctypes.Structure):
    _fields_ = [('guid', ctypes.c_byte * 16),
               ('description', wintypes.WCHAR * 256),
               ('state', wintypes.DWORD)]


def enumerate_wlan_interfaces():
    """Use the Windows WLAN API, independent of display language."""
    api = ctypes.WinDLL('wlanapi')
    api.WlanOpenHandle.argtypes = [wintypes.DWORD, ctypes.c_void_p,
                                  ctypes.POINTER(wintypes.DWORD),
                                  ctypes.POINTER(wintypes.HANDLE)]
    api.WlanOpenHandle.restype = wintypes.DWORD
    api.WlanEnumInterfaces.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                      ctypes.POINTER(ctypes.c_void_p)]
    api.WlanEnumInterfaces.restype = wintypes.DWORD
    api.WlanFreeMemory.argtypes = [ctypes.c_void_p]
    api.WlanFreeMemory.restype = None
    api.WlanCloseHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    api.WlanCloseHandle.restype = wintypes.DWORD
    handle, version = wintypes.HANDLE(), wintypes.DWORD()
    code = api.WlanOpenHandle(2, None, ctypes.byref(version),
                              ctypes.byref(handle))
    if code:
        raise ctypes.WinError(code)
    pointer = ctypes.c_void_p()
    try:
        code = api.WlanEnumInterfaces(handle, None, ctypes.byref(pointer))
        if code:
            raise ctypes.WinError(code)
        if not pointer.value:
            raise RuntimeError('WLAN returned no interface list.')
        count = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))[0]
        if count > 256:
            raise RuntimeError('Invalid WLAN interface count.')
        address = pointer.value + 2 * ctypes.sizeof(wintypes.DWORD)
        entries = (InterfaceInfo * count).from_address(address)
        return [{'name': entry.description, 'state': int(entry.state)}
                for entry in entries]
    finally:
        if pointer.value:
            api.WlanFreeMemory(pointer)
        api.WlanCloseHandle(handle, None)


def check_wifi_status():
    try:
        interfaces = enumerate_wlan_interfaces()
    except Exception as exc:
        return 'error', 'Cannot query WLAN interfaces/service: {}'.format(exc), []
    if not interfaces:
        return 'unavailable', ('No enabled WLAN interface was found. Check '
                               'adapter enablement and drivers.'), []
    ready = [entry for entry in interfaces if entry['state'] != 0]
    if not ready:
        return 'unavailable', 'WLAN interface detected but not ready.', interfaces
    return 'pass', ('Wi-Fi adapter detected: {}. Connection, signal, speed and '
                    'internet access were not tested.').format(
                        ', '.join(entry['name'] for entry in ready)), interfaces


def check_wifi_available():
    """Compatibility wrapper for consumers needing a detection result."""
    state, detail, _ = check_wifi_status()
    return state == 'pass', detail


def run_wifi_test(root, test_results, test_labels, tests_window=None,
                  completion_event=None):
    from services.hardware_job import JobPoller

    def complete(reply):
        state = reply.get('state', 'error')
        detail = reply.get('detail', '')
        interfaces = reply.get('interfaces', [])
        test_results['wifi'] = state
        record_coverage(test_results, 'wifi',
                        'Enabled WLAN adapter detection only; network quality '
                        'and connectivity untested.',
                        {'source': 'Windows WLAN API', 'interfaces': interfaces,
                         'detail': detail})
        log_event('Wi-Fi adapter detection {}: {}'.format(state, detail))
        if tests_window:
            tests_window.update_icon('wifi')
            tests_window.update_status({
                'pass': 'Wi-Fi adapter detected.',
                'unavailable': 'Wi-Fi adapter unavailable. Check that Wi-Fi is enabled.',
                'error': 'Wi-Fi check could not complete. Retry the check.',
            }.get(state, 'Wi-Fi check did not complete.'))
        elif 'wifi_label' in test_labels:
            test_labels['wifi_label'].config(text=state.upper())
        if completion_event:
            completion_event.set()
    job = JobPoller(root, 'wifi', complete, timeout=15)

    def cancel():
        job.cancel()
        test_results['wifi'] = 'cancelled'
        if completion_event:
            completion_event.set()
    if tests_window and hasattr(tests_window, 'register_cancel'):
        tests_window.register_cancel(cancel)
    return type('WifiCheck', (), {'cancel': staticmethod(cancel)})()
