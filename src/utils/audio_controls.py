"""Windows audio helpers for hardware tests."""

from __future__ import annotations

import ctypes
import sys
import uuid
from typing import Optional

from utils.helpers import log_event

HRESULT = ctypes.c_long
CLSCTX_ALL = 23
COINIT_APARTMENTTHREADED = 0x2
S_OK = 0
S_FALSE = 1
RPC_E_CHANGED_MODE = 0x80010106

eRender = 0
EDataFlow_capture = 1
ERole_console = 0


class GUID(ctypes.Structure):
    """Minimal GUID implementation for COM interactions."""

    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_uint8 * 8),
    ]

    @classmethod
    def from_string(cls, guid: str) -> "GUID":
        parsed = uuid.UUID(guid)
        instance = cls()
        instance.Data1 = parsed.time_low
        instance.Data2 = parsed.time_mid
        instance.Data3 = parsed.time_hi_version
        data4 = (ctypes.c_uint8 * 8).from_buffer_copy(parsed.bytes[8:])
        for idx in range(8):
            instance.Data4[idx] = data4[idx]
        return instance


CLSID_MMDeviceEnumerator = GUID.from_string("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
IID_IMMDeviceEnumerator = GUID.from_string("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
IID_IAudioEndpointVolume = GUID.from_string("{5CDF2C82-841E-4546-9722-0CF74078229A}")


if sys.platform == "win32":
    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole32.CoInitializeEx.restype = HRESULT
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(GUID),
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = HRESULT
else:  # pragma: no cover - executed on non-Windows platforms
    ole32 = None


class VolumeAdjustmentError(RuntimeError):
    """Raised when the system audio levels cannot be adjusted."""


def _format_hresult(hr: int) -> str:
    return f"0x{ctypes.c_uint32(hr).value:08X}"


def _get_vtable_method(instance: ctypes.c_void_p, index: int, restype, *argtypes):
    vtable = ctypes.cast(instance, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    function_type = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return function_type(vtable[index])


def _release(instance: Optional[ctypes.c_void_p]) -> None:
    if not instance or not getattr(instance, "value", None):
        return
    try:
        method = _get_vtable_method(instance, 2, ctypes.c_ulong)
        method(instance)
    except Exception:  # pragma: no cover - release best effort
        pass


def _initialise_com() -> bool:
    if ole32 is None:
        raise VolumeAdjustmentError("Volume adjustment is only supported on Windows.")

    result = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    if result in (S_OK, S_FALSE):
        return True
    if result == RPC_E_CHANGED_MODE:
        return False
    raise VolumeAdjustmentError(f"CoInitializeEx failed with {_format_hresult(result)}")


def _set_endpoint_volume(data_flow: int, label: str) -> None:
    if ole32 is None:
        raise VolumeAdjustmentError("COM library not available for volume control.")

    enumerator = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(
        ctypes.byref(CLSID_MMDeviceEnumerator),
        None,
        CLSCTX_ALL,
        ctypes.byref(IID_IMMDeviceEnumerator),
        ctypes.byref(enumerator),
    )
    if hr != S_OK:
        raise VolumeAdjustmentError(
            f"Failed to create MMDeviceEnumerator for {label}: {_format_hresult(hr)}"
        )

    try:
        device = ctypes.c_void_p()
        get_default = _get_vtable_method(
            enumerator,
            4,
            HRESULT,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p),
        )
        hr = get_default(enumerator, data_flow, ERole_console, ctypes.byref(device))
        if hr != S_OK:
            raise VolumeAdjustmentError(
                f"Unable to access default {label} endpoint: {_format_hresult(hr)}"
            )

        try:
            endpoint_volume = ctypes.c_void_p()
            activate = _get_vtable_method(
                device,
                3,
                HRESULT,
                ctypes.POINTER(GUID),
                ctypes.c_uint,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            )
            hr = activate(
                device,
                ctypes.byref(IID_IAudioEndpointVolume),
                CLSCTX_ALL,
                None,
                ctypes.byref(endpoint_volume),
            )
            if hr != S_OK:
                raise VolumeAdjustmentError(
                    f"Unable to activate endpoint volume for {label}: {_format_hresult(hr)}"
                )

            try:
                get_channel_count = _get_vtable_method(
                    endpoint_volume, 5, HRESULT, ctypes.POINTER(ctypes.c_uint)
                )
                set_master_scalar = _get_vtable_method(
                    endpoint_volume, 7, HRESULT, ctypes.c_float, ctypes.c_void_p
                )
                set_channel_scalar = _get_vtable_method(
                    endpoint_volume,
                    11,
                    HRESULT,
                    ctypes.c_uint,
                    ctypes.c_float,
                    ctypes.c_void_p,
                )

                channel_count = ctypes.c_uint()
                hr = get_channel_count(endpoint_volume, ctypes.byref(channel_count))
                if hr != S_OK:
                    raise VolumeAdjustmentError(
                        f"Failed to read channel count for {label}: {_format_hresult(hr)}"
                    )

                volume_level = ctypes.c_float(1.0)
                hr = set_master_scalar(endpoint_volume, volume_level, None)
                if hr != S_OK:
                    raise VolumeAdjustmentError(
                        f"Failed to set master volume for {label}: {_format_hresult(hr)}"
                    )

                for channel in range(channel_count.value):
                    hr = set_channel_scalar(
                        endpoint_volume,
                        channel,
                        volume_level,
                        None,
                    )
                    if hr != S_OK:
                        raise VolumeAdjustmentError(
                            f"Failed to set channel {channel} volume for {label}: {_format_hresult(hr)}"
                        )
            finally:
                _release(endpoint_volume)
        finally:
            _release(device)
    finally:
        _release(enumerator)


def force_max_system_volume() -> bool:
    """Set default speaker and microphone levels to 100% for the hardware test."""

    if sys.platform != "win32":  # pragma: no cover - Windows-specific functionality
        log_event("Automatic volume adjustment is only supported on Windows.")
        return False

    try:
        should_uninit = _initialise_com()
    except VolumeAdjustmentError as exc:
        log_event(f"Unable to initialise audio controls: {exc}")
        return False

    errors = []
    try:
        try:
            _set_endpoint_volume(eRender, "speaker")
        except VolumeAdjustmentError as exc:
            errors.append(str(exc))
        try:
            _set_endpoint_volume(EDataFlow_capture, "microphone")
        except VolumeAdjustmentError as exc:
            errors.append(str(exc))
    finally:
        if should_uninit:
            ole32.CoUninitialize()

    if errors:
        log_event("Automatic volume adjustment encountered issues: " + "; ".join(errors))
        return False

    log_event("Speaker and microphone levels forced to maximum before test.")
    return True
