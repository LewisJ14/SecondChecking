from services.operator_session import headers as operator_session_headers
import configparser
import datetime
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import wmi
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import requests
from services import transport
from services import operator_session

SYSROOT = Path(os.environ.get("WINDIR", r"C:\Windows"))
DSREGCMD_PATH = SYSROOT / "System32" / "dsregcmd.exe"
GPUPDATE_PATH = SYSROOT / "System32" / "gpupdate.exe"

_SKU_TAG_METADATA: Optional[List[Dict[str, Any]]] = None
_DROPDOWN_OPTION_CACHE: Optional[Dict[int, Dict[str, str]]] = None
_ADMIN_SKU_RULES: Optional[List[Dict[str, Any]]] = None
_ADMIN_SKU_RULES_LOADED_AT = 0.0
_CPU_KEYWORD_TOKENS: Optional[Set[str]] = None
_NORMALIZE_PATTERN = re.compile(r"[^A-Z0-9]+")
_STORAGE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(TB|GB)\b", re.IGNORECASE)
_CATEGORY_TO_SPEC_FIELD = {
    "cpu": "CPU",
    "memory": "RAM",
    "storage": "SSD",
    "os": "Windows",
    "battery": "Battery",
    "model": "Model",
    "resolution": "Resolution",
}


def _windows_no_window_creationflags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


def _run_windows_command(path: Path, args: list[str], label: str) -> bool:
    """Run `path` with `args`, logging the result."""

    if not path.exists():
        log_event(f"{label} ({path}) not found; skipping.")
        return False

    try:
        result = subprocess.run(
            [str(path), *args],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=_windows_no_window_creationflags(),
        )
        if result.returncode == 0:
            log_event(f"{label} succeeded with args {args}.")
            return True
        log_event(
            f"{label} exited {result.returncode}: {(result.stderr or result.stdout).strip()}"
        )
    except subprocess.TimeoutExpired as exc:
        log_event(f"The command {label} timed out: {exc}")
    except Exception as exc:  # noqa: BLE001 - log for supportability
        log_event(f"Failed to run {label}: {exc}")

    return False


def run_mdm_policy_commands() -> bool:
    """Run dsregcmd /sync and gpupdate /force to refresh Windows policies."""

    if sys.platform != "win32":
        return False

    success = _run_windows_command(DSREGCMD_PATH, ["/sync"], "dsregcmd /sync")
    success |= _run_windows_command(GPUPDATE_PATH, ["/force"], "gpupdate /force")
    if not success:
        log_event("Unable to trigger policy refresh via dsregcmd/gpupdate.")

    return success


def capture_autopilot_hash_csv(
    preferred_serial: Optional[str] = None,
    output_directory: Optional[str] = None,
) -> Optional[str]:
    """
    Capture the Autopilot hardware hash CSV using the same CIM/MDM bridge
    method as HashCollector. Returns the CSV path when successful.
    """

    if sys.platform != "win32":
        log_event("Autopilot hash capture skipped: Windows only.")
        return None

    out_dir = output_directory or os.path.join(get_app_dir(), "AutopilotHashes")
    os.makedirs(out_dir, exist_ok=True)

    script = r"""
param(
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [string]$PreferredSerial = ""
)
$ErrorActionPreference = "Stop"

if (-not [Environment]::Is64BitProcess) {
    $argsList = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-Command", $MyInvocation.Line
    )
    & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" @argsList
    exit $LASTEXITCODE
}

if (-not (Test-Path -LiteralPath $OutputDirectory)) {
    New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
}

$serial = (Get-CimInstance -ClassName Win32_BIOS).SerialNumber
if ([string]::IsNullOrWhiteSpace($serial) -and -not [string]::IsNullOrWhiteSpace($PreferredSerial)) {
    $serial = $PreferredSerial
}
if ([string]::IsNullOrWhiteSpace($serial)) {
    throw "Serial number not found."
}
$serial = $serial.Trim()

$winProdId = (Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion" -Name ProductId).ProductId

function Get-HashFromInstances {
    param([object]$Instances)
    if ($null -eq $Instances) { return $null }

    $list = @($Instances)
    foreach ($item in $list) {
        if ($null -eq $item) { continue }
        $raw = $null
        try { $raw = $item.DeviceHardwareData } catch {}
        if ($null -eq $raw) { continue }

        if ($raw -is [byte[]]) {
            $hash = [Convert]::ToBase64String($raw)
        } else {
            $hash = [string]$raw
        }
        if (-not [string]::IsNullOrWhiteSpace($hash)) {
            return $hash.Trim()
        }
    }
    return $null
}

function Try-GetHashFromSource {
    param(
        [Parameter(Mandatory = $true)][string]$ClassName,
        [string]$Filter = ""
    )

    $instances = $null
    try {
        if ([string]::IsNullOrWhiteSpace($Filter)) {
            $instances = Get-CimInstance -Namespace "root\cimv2\mdm\dmmap" -ClassName $ClassName -ErrorAction Stop
        } else {
            $instances = Get-CimInstance -Namespace "root\cimv2\mdm\dmmap" -ClassName $ClassName -Filter $Filter -ErrorAction Stop
        }
        $hash = Get-HashFromInstances -Instances $instances
        if (-not [string]::IsNullOrWhiteSpace($hash)) { return $hash }
    } catch {}

    try {
        if ([string]::IsNullOrWhiteSpace($Filter)) {
            $instances = Get-WmiObject -Namespace "root\cimv2\mdm\dmmap" -Class $ClassName -ErrorAction Stop
        } else {
            $instances = Get-WmiObject -Namespace "root\cimv2\mdm\dmmap" -Class $ClassName -Filter $Filter -ErrorAction Stop
        }
        $hash = Get-HashFromInstances -Instances $instances
        if (-not [string]::IsNullOrWhiteSpace($hash)) { return $hash }
    } catch {}

    return $null
}

function Get-HardwareHash {
    $hash = Try-GetHashFromSource -ClassName "MSFT_AutopilotDeviceInformation"
    if (-not [string]::IsNullOrWhiteSpace($hash)) { return $hash }

    $hash = Try-GetHashFromSource -ClassName "MSFT_AutopilotDeviceInformation" -Filter "ParentID='./DevDetail'"
    if (-not [string]::IsNullOrWhiteSpace($hash)) { return $hash }

    $hash = Try-GetHashFromSource -ClassName "MDM_DevDetail_Ext01"
    if (-not [string]::IsNullOrWhiteSpace($hash)) { return $hash }

    $hash = Try-GetHashFromSource -ClassName "MDM_DevDetail_Ext01" -Filter "InstanceID='Ext' AND ParentID='./DevDetail'"
    if (-not [string]::IsNullOrWhiteSpace($hash)) { return $hash }

    # Optional fallback for systems where the Microsoft script is already available.
    try {
        $cmd = Get-Command -Name "Get-WindowsAutopilotInfo" -ErrorAction SilentlyContinue
        if ($null -ne $cmd) {
            $tmpCsv = Join-Path -Path $env:TEMP -ChildPath ("autopilot_hash_{0}.csv" -f ([guid]::NewGuid().ToString("N")))
            Get-WindowsAutopilotInfo -OutputFile $tmpCsv -ErrorAction Stop | Out-Null
            if (Test-Path -LiteralPath $tmpCsv) {
                $csvRow = Import-Csv -LiteralPath $tmpCsv | Select-Object -First 1
                if ($null -ne $csvRow) {
                    $csvHash = [string]$csvRow."Hardware Hash"
                    if (-not [string]::IsNullOrWhiteSpace($csvHash)) {
                        Remove-Item -LiteralPath $tmpCsv -Force -ErrorAction SilentlyContinue
                        return $csvHash.Trim()
                    }
                }
                Remove-Item -LiteralPath $tmpCsv -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {}

    # Fallback using mdmdiagnosticstool Autopilot report (when available).
    try {
        $mdmDiag = Join-Path -Path $env:SystemRoot -ChildPath "System32\mdmdiagnosticstool.exe"
        $expandExe = Join-Path -Path $env:SystemRoot -ChildPath "System32\expand.exe"
        if ((Test-Path -LiteralPath $mdmDiag) -and (Test-Path -LiteralPath $expandExe)) {
            $guid = [guid]::NewGuid().ToString("N")
            $cabPath = Join-Path -Path $env:TEMP -ChildPath ("autopilot_diag_{0}.cab" -f $guid)
            $extractDir = Join-Path -Path $env:TEMP -ChildPath ("autopilot_diag_{0}" -f $guid)
            New-Item -ItemType Directory -Path $extractDir -Force | Out-Null

            & $mdmDiag -area Autopilot -cab $cabPath | Out-Null
            if (Test-Path -LiteralPath $cabPath) {
                & $expandExe -F:* $cabPath $extractDir | Out-Null
                $csvCandidates = Get-ChildItem -Path $extractDir -Recurse -File -ErrorAction SilentlyContinue |
                    Where-Object { $_.Extension -ieq ".csv" }

                foreach ($csvFile in $csvCandidates) {
                    try {
                        $rows = Import-Csv -LiteralPath $csvFile.FullName -ErrorAction Stop
                        foreach ($r in $rows) {
                            $diagHash = [string]$r."Hardware Hash"
                            if (-not [string]::IsNullOrWhiteSpace($diagHash)) {
                                try { Remove-Item -LiteralPath $cabPath -Force -ErrorAction SilentlyContinue } catch {}
                                try { Remove-Item -LiteralPath $extractDir -Recurse -Force -ErrorAction SilentlyContinue } catch {}
                                return $diagHash.Trim()
                            }
                        }
                    } catch {}
                }
            }

            try { Remove-Item -LiteralPath $cabPath -Force -ErrorAction SilentlyContinue } catch {}
            try { Remove-Item -LiteralPath $extractDir -Recurse -Force -ErrorAction SilentlyContinue } catch {}
        }
    } catch {}

    throw "Hardware hash not available via MDM Bridge, Get-WindowsAutopilotInfo, or mdmdiagnosticstool."
}

$hw = Get-HardwareHash
$hw64 = [string]$hw
if ([string]::IsNullOrWhiteSpace($hw64)) {
    throw "Hardware hash empty."
}

$row = [PSCustomObject]@{
    "Device Serial Number" = $serial
    "Windows Product ID"   = $winProdId
    "Hardware Hash"        = $hw64
}

$safeSerial = ($serial -replace '[\\/:*?"<>|]', "_")
$outFile = Join-Path -Path $OutputDirectory -ChildPath ("{0}.csv" -f $safeSerial)
$row | Export-Csv -Path $outFile -NoTypeInformation -Encoding UTF8
Write-Output $outFile
"""

    temp_script_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".ps1",
            delete=False,
        ) as temp_script:
            temp_script.write(script)
            temp_script_path = temp_script.name

        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            temp_script_path,
            "-OutputDirectory",
            out_dir,
            "-PreferredSerial",
            preferred_serial or "",
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=_windows_no_window_creationflags(),
        )
    except Exception as exc:  # noqa: BLE001
        log_event(f"Autopilot hash capture failed to start: {exc}")
        return None
    finally:
        if temp_script_path:
            try:
                os.remove(temp_script_path)
            except OSError:
                pass

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        failure_text = stderr or stdout or f"exit code {result.returncode}"
        if stderr:
            lines = [line.strip() for line in stderr.splitlines() if line.strip()]
            primary = next((line for line in lines if not line.startswith("At ")), "")
            if primary:
                failure_text = primary
        log_event(
            "Autopilot hash capture failed: " + failure_text
        )
        return None

    output = (result.stdout or "").strip().splitlines()
    csv_path = output[-1].strip() if output else ""
    if not csv_path or not os.path.exists(csv_path):
        log_event(f"Autopilot hash capture completed but CSV path was not found: '{csv_path}'")
        return None

    log_event(f"Autopilot hash CSV created: {csv_path}")
    return csv_path


def upload_hash_csv(
    file_path,
    serial_id=None,
    order_id=None,
    serial_number=None,
    sku=None,
    uploaded_at=None,
):
    """
    Upload a hash CSV file to Web-Tools using multipart/form-data.

    Local test example:
    upload_hash_csv(r"C:\\temp\\PF24NEM2.csv", serial_id=123, uploaded_at="2026-03-18T10:00:00Z")
    """

    identifier_text = ""
    if serial_id is not None:
        identifier_text = f"serial_id={serial_id}"
    elif order_id is not None and serial_number:
        identifier_text = f"order_id={order_id},serial_number={serial_number}"
    else:
        log_event("Hash upload skipped: missing serial identifier (serial_id or order_id+serial_number).")
        return False
    sku_text = str(sku or "").strip()
    if sku_text:
        identifier_text = f"{identifier_text},sku={sku_text}"

    if not file_path or not os.path.exists(file_path):
        log_event(f"Hash upload skipped: file not found ({file_path}).")
        return False

    base_url, api_key = _load_webtools_api_config()
    if not api_key or api_key == "<SECRET>":
        log_event("Hash upload skipped: X-Second-Check-Key is not configured.")
        return False
    url = f"{base_url.rstrip('/')}/orders/serials/hash"
    file_name = os.path.basename(file_path)
    utc_stamp = uploaded_at or datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

    form_data = {"hash_uploaded_at": utc_stamp}
    if serial_id is not None:
        form_data["serial_id"] = str(serial_id)
    else:
        form_data["order_id"] = str(order_id)
        form_data["serial_number"] = str(serial_number)
    if sku_text:
        form_data["sku"] = sku_text

    headers = {"X-Second-Check-Key": api_key}
    from services.operator_session import headers as session_headers
    headers.update(session_headers(base_url))
    max_attempts = 4
    backoff_seconds = 1

    for attempt in range(1, max_attempts + 1):
        try:
            with open(file_path, "rb") as csv_handle:
                response = transport.post(
                    url,
                    headers=headers,
                    data=form_data,
                    files={"hash_file": (file_name, csv_handle, "text/csv")},
                    timeout=20,
                )
        except requests.RequestException as exc:
            if attempt < max_attempts:
                log_event(
                    f"Hash upload retry ({attempt}/{max_attempts}) {identifier_text} file={file_name} network_error={exc}"
                )
                time.sleep(backoff_seconds)
                backoff_seconds *= 2
                continue
            log_event(f"Hash upload failed {identifier_text} file={file_name} network_error={exc}")
            return False

        status = response.status_code
        log_event(f"Hash upload response {identifier_text} file={file_name} status={status}")

        if status == 200:
            log_event(f"Hash upload success {identifier_text} file={file_name}")
            return True

        if status in {500, 502, 503, 504} and attempt < max_attempts:
            log_event(
                f"Hash upload retry ({attempt}/{max_attempts}) {identifier_text} file={file_name} status={status}"
            )
            time.sleep(backoff_seconds)
            backoff_seconds *= 2
            continue

        if status == 400:
            log_event(f"Hash upload failed {identifier_text} file={file_name} status=400 payload/format issue")
            return False
        if status == 401:
            log_event(f"Hash upload failed {identifier_text} file={file_name} status=401 auth issue")
            return False
        if status == 404:
            log_event(f"Hash upload failed {identifier_text} file={file_name} status=404 serial not found")
            return False
        if status >= 500:
            log_event(f"Hash upload failed {identifier_text} file={file_name} status={status} server error")
            return False

        log_event(f"Hash upload failed {identifier_text} file={file_name} status={status}")
        return False

    log_event(f"Hash upload failed {identifier_text} file={file_name} retries exhausted")
    return False


def _load_webtools_api_config():
    from services.configuration import webtools_settings
    # API callers already handle an absent key without issuing a request.
    try:
        return webtools_settings(load_config())
    except Exception:
        log_event("Web-Tools configuration invalid; check SECOND_CHECK_BASE_URL and SECOND_CHECK_KEY.")
        return "", ""


def upload_stock_unit_check_report(
    *,
    order_id,
    order_number,
    serial_number,
    sku,
    specs,
    test_results,
    test_overrides=None,
    test_coverage=None,
    assignment_review=None,
    storage_review=None,
    mdm_status=None,
    assigned_by=None,
    hash_csv_path=None,
    battery_report=None,
    checked_at=None,
    create_stock_unit=False,
    reassignment_prompt=None,
):
    """Upload the full SecondChecking result to the Web-Tools stock-unit API."""

    serial_text = str(serial_number or "").strip()
    if not serial_text or serial_text == "Unknown":
        log_event("Stock report upload skipped: missing serial number.")
        return False, {"error": "missing serial number"}

    base_url, api_key = _load_webtools_api_config()
    if not api_key or api_key == "<SECRET>":
        log_event("Stock report upload skipped: X-Second-Check-Key is not configured.")
        return False, {"error": "missing API key"}

    utc_stamp = checked_at or datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    hash_filename = ""
    hash_text = ""
    if hash_csv_path:
        if os.path.exists(hash_csv_path):
            hash_filename = os.path.basename(hash_csv_path)
            try:
                with open(hash_csv_path, "r", encoding="utf-8-sig") as handle:
                    hash_text = handle.read()
            except UnicodeDecodeError:
                with open(hash_csv_path, "r", encoding="utf-8", errors="ignore") as handle:
                    hash_text = handle.read()
            except OSError as exc:
                log_event(f"Stock report hash read failed: {exc}")
        else:
            log_event(f"Stock report hash file not found: {hash_csv_path}")

    from services.mdm_evidence import qualified

    payload = {
        "order_id": order_id,
        "order_number": order_number,
        "serial_number": serial_text,
        "sku": sku,
        "specs": {key: value for key, value in (specs or {}).items() if not key.startswith("_")},
        "test_results": test_results or {},
        "result_policy_version": 1,
        "test_overrides": test_overrides or {},
        "test_coverage": test_coverage or {},
        "assignment_review": assignment_review or {},
        "storage_review": storage_review or {},
        "mdm": qualified(mdm_status),
        "activation": (test_results or {}).get("activation"),
        "assigned_by": assigned_by,
        "checked_at": utc_stamp,
        "hash_uploaded_at": utc_stamp,
        "hash_filename": hash_filename,
        "hash_file_data": hash_text,
        "battery_report": battery_report or {},
        "create_stock_unit": bool(create_stock_unit),
    }

    from services.assignment_api import post_assignment

    return post_assignment(
        base_url, api_key, "/api/stock_units/check-report", payload,
        reassignment_prompt=reassignment_prompt,
    )


def load_saved_check_results(order_number, serial_number):
    """Read result provenance from the same service that saved the report."""
    base_url, api_key = _load_webtools_api_config()
    if not api_key or api_key == "<SECRET>":
        raise ValueError("Configure the SecondChecking API key to load saved results.")
    generation = operator_session.generation()
    session_headers = operator_session_headers(base_url)
    if not session_headers:
        operator_session.clear_if_current(generation)
        raise operator_session.SignInRequired()
    response = transport.get(
        base_url + "/api/stock_units/second-check-results",
        params={"order_number": order_number, "serial_number": serial_number},
        headers=dict({"X-Second-Check-Key": api_key}, **session_headers), timeout=15,
    )
    if response.status_code == 401:
        operator_session.clear_if_current(generation)
        raise operator_session.SignInRequired()
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or body.get("success") is not True:
        raise ValueError("Web-Tools did not confirm the saved check results.")
    if not isinstance(body.get("found"), bool):
        raise ValueError("Web-Tools did not confirm whether a saved report exists.")
    return body


def unassign_order_serial(order_number, serial_number, assigned_by=None):
    from services.assignment_api import post_assignment

    base_url, api_key = _load_webtools_api_config()
    if not api_key or api_key == "<SECRET>":
        return False, {"error": "missing API key"}
    return post_assignment(base_url, api_key, "/api/stock_units/unassign", {
        "order_number": order_number,
        "serial_number": serial_number,
        "assigned_by": assigned_by,
    })


def log_event(message):
    from services.runtime import log_event as write_log
    write_log(message)

def get_config_path():
    # Determine the path to the configuration file
    from services.configuration import config_path
    return str(config_path())


def get_log_path():
    from services.runtime import log_path
    return str(log_path())


def get_app_dir():
    from services.runtime import app_directory
    return str(app_directory())

def load_config():
    from services.configuration import read_config
    return read_config()


def parse_percent(text):
    match = re.search(r"(?<![\d.,-])(\d+(?:[.,]\d+)?)\s*%", str(text or ""))
    if match:
        return float(match.group(1).replace(",", "."))
    return None


def check_activation_status():
    """
    Check if Windows is permanently activated using slmgr.vbs /xpr.
    Returns True if activated, False otherwise.
    """
    try:
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(
            ['cscript.exe', '//Nologo', 'C:\\Windows\\System32\\slmgr.vbs', '/xpr'],
            capture_output=True, text=True, timeout=10, creationflags=creationflags
        )
        output = result.stdout.lower()
        # Check for the activation confirmation message
        if "permanently activated" in output:
            return True
        log_event(f"[DEBUG] slmgr /xpr output: {output}")
    except Exception as e:
        log_event(f"check_activation_status error: {e}")
    return False


def is_internet_available(timeout: int = 5) -> bool:
    """Return True when outbound HTTP requests succeed within the timeout."""

    test_urls = (
        "https://www.msftconnecttest.com/connecttest.txt",
        "https://www.google.com/generate_204",
    )

    failures = []
    for url in test_urls:
        try:
            with urllib.request.urlopen(url, timeout=timeout):
                return True
        except Exception as exc:  # noqa: BLE001 - logging the specific failure
            failures.append(f"{url}: {exc}")
    for failure in failures:
        log_event(f"Internet connectivity probe failed: {failure}")
    return False


def check_mdm_lock_status() -> Dict[str, Any]:
    """Read local Autopilot evidence without asserting tenant/lock status."""
    from services.mdm_evidence import evidence

    if sys.platform != "win32":
        return evidence("unsupported", "The local registry check requires Windows.")

    import winreg

    path = r"SOFTWARE\Microsoft\Provisioning\Diagnostics\Autopilot"
    observations = {}
    errors = []
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0,
                             winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
    except FileNotFoundError:
        return evidence("no_local_indicators", "Diagnostics registry key is absent.",
                        key_present=False)
    except OSError as exc:
        return evidence("error", "Diagnostics registry key could not be opened.",
                        read_errors=[str(exc)])

    def read_value(handle, name):
        try:
            value, _ = winreg.QueryValueEx(handle, name)
            if not isinstance(value, str):
                errors.append(name + ": unexpected registry value type")
            elif value.strip():
                observations[name] = value.strip()
        except FileNotFoundError:
            pass
        except OSError as exc:
            errors.append(name + ": " + str(exc))

    try:
        for name in ("CloudAssignedTenantId", "CloudAssignedTenantDomain"):
            read_value(key, name)
        try:
            correlations = winreg.OpenKey(key, "EstablishedCorrelations")
        except FileNotFoundError:
            correlations = None
        except OSError as exc:
            correlations = None
            errors.append("EstablishedCorrelations: " + str(exc))
        if correlations is not None:
            try:
                for name in ("EntDMID", "ZTDRegistrationID"):
                    read_value(correlations, name)
            finally:
                winreg.CloseKey(correlations)
    finally:
        winreg.CloseKey(key)

    state = "local_indicators" if observations else ("error" if errors else "no_local_indicators")
    details = (" | ".join(name + ": " + value for name, value in observations.items())
               if observations else "No local tenant or registration identifiers were observed.")
    log_event("Local Autopilot evidence result: " + state)
    return evidence(state, details, observations=observations, read_errors=errors,
                    key_present=True)


def refresh_mdm_lock_status() -> Dict[str, Any]:
    """Re-read local evidence; policy commands do not verify tenant registration."""
    return check_mdm_lock_status()


def _normalize_string(value: Optional[Any]) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def _normalize_token(token: Optional[str]) -> str:
    if not token:
        return ""
    return _NORMALIZE_PATTERN.sub("", token.upper())


def _get_cpu_keyword_tokens() -> Set[str]:
    """Cache the normalized CPU keywords defined in config."""
    global _CPU_KEYWORD_TOKENS
    if _CPU_KEYWORD_TOKENS is not None:
        return _CPU_KEYWORD_TOKENS
    try:
        config = load_config()
    except Exception:
        _CPU_KEYWORD_TOKENS = set()
        return _CPU_KEYWORD_TOKENS
    raw_keywords = config.get("search", "cpu_keywords", fallback="")
    tokens = {_normalize_token(keyword) for keyword in raw_keywords.split(",") if keyword.strip()}
    _CPU_KEYWORD_TOKENS = {token for token in tokens if token}
    return _CPU_KEYWORD_TOKENS


def is_generic_cpu_spec(value: Optional[str]) -> bool:
    """Return True when the SKU CPU spec matches a known generic keyword."""
    token = _normalize_token(value)
    return bool(token and token in _get_cpu_keyword_tokens())


def cpu_specs_are_compatible(sku_spec: Optional[str], laptop_spec: Optional[str]) -> bool:
    """Use SKU keywords to confirm when generic specs should match verbose names."""
    if sku_spec and ',' in sku_spec:
        return any(cpu_specs_are_compatible(option.strip(), laptop_spec)
                   for option in sku_spec.split(',') if option.strip())
    sku_token = _normalize_token(sku_spec)
    laptop_token = _normalize_token(laptop_spec)
    if not sku_token or not laptop_token:
        return False
    if sku_token == laptop_token:
        return True
    # WMI may include the manufacturer and clock speed around an exact model.
    model = re.fullmatch(r'i[3579]-\d{3,5}[a-z0-9]*', str(sku_spec).strip(), re.I)
    if model and re.search(r'(?<![a-z0-9])' + re.escape(model.group())
                           + r'(?![a-z0-9])', str(laptop_spec), re.I):
        return True
    if is_generic_cpu_spec(sku_spec):
        return sku_token in laptop_token
    return False


def specification_matches(field, expected, actual):
    """Compare explicit aliases without treating model substrings as matches."""
    if field == 'CPU':
        return cpu_specs_are_compatible(expected, actual)
    for alias in str(expected).split(','):
        left, right = alias.strip(), str(actual).strip()
        if field == 'Model':
            def model_token(value):
                value = re.sub(r'^thinkpad\s+', '', value, flags=re.I)
                value = re.sub(r'\s+notebook\s+pc$', '', value, flags=re.I)
                return _normalize_token(value)
            if model_token(left) and model_token(left) == model_token(right):
                return True
        elif field == 'Windows':
            # A generic OS requirement accepts editions, an explicit edition does not.
            if re.fullmatch(r'Windows\s+(10|11)', left, re.I):
                if re.fullmatch(re.escape(left) + r'(?:\s+(?:Home|Pro|Enterprise|Education))?', right, re.I):
                    return True
            elif left.casefold() == right.casefold():
                return True
        elif left.casefold() == right.casefold():
            return True
    return False


def _storage_capacity_to_gb(value: Optional[str]) -> Optional[int]:
    from services.storage import parse_configuration

    drives = parse_configuration(value)
    if drives is None or len(drives) != 1:
        return None
    return round(drives[0]["size_bytes"] / 10**9)


def storage_specs_are_compatible(sku_spec, laptop_spec, captured=None):
    from services.storage import compare_storage

    return compare_storage(sku_spec, laptop_spec, captured)[0]


def _build_dropdown_option_cache(cursor) -> Dict[int, Dict[str, str]]:
    global _DROPDOWN_OPTION_CACHE
    if _DROPDOWN_OPTION_CACHE is not None:
        return _DROPDOWN_OPTION_CACHE
    cache: Dict[int, Dict[str, str]] = {}
    try:
        cursor.execute("SELECT id, category, name FROM dropdown_option")
        for dropdown_id, category, name in cursor.fetchall():
            if dropdown_id is None:
                continue
            cache[int(dropdown_id)] = {
                "category": _normalize_string(category).lower(),
                "name": _normalize_string(name),
            }
    except Exception as exc:  # pragma: no cover - best-effort metadata load
        log_event(f"Failed to load dropdown options: {exc}")
    _DROPDOWN_OPTION_CACHE = cache
    return cache


def _load_sku_tag_metadata(cursor) -> List[Dict[str, Any]]:
    global _SKU_TAG_METADATA
    if _SKU_TAG_METADATA is not None:
        return _SKU_TAG_METADATA
    cache: List[Dict[str, Any]] = []
    dropdown_cache = _build_dropdown_option_cache(cursor)
    try:
        cursor.execute(
            """
            SELECT
                atm.attribute_id,
                atm.term_id,
                atm.sku_tag,
                atm.astro_name,
                atm.dropdown_option_id,
                adm.dropdown_category
            FROM attribute_term_metadata atm
            LEFT JOIN attribute_dropdown_map adm
                ON atm.attribute_id = adm.attribute_id
            """
        )
        for row in cursor.fetchall():
            attribute_id, term_id, sku_tag, astro_name, dropdown_option_id, dropdown_category = row
            sku_tag_str = _normalize_string(sku_tag)
            if not sku_tag_str:
                continue
            option_info = {}
            if dropdown_option_id is not None:
                option_info = dropdown_cache.get(int(dropdown_option_id), {})
            category = _normalize_string(dropdown_category) or option_info.get("category") or ""
            entry = {
                "attribute_id": attribute_id,
                "term_id": term_id,
                "sku_tag": sku_tag_str,
                "normalized_tag": _normalize_token(sku_tag_str),
                "astro_name": _normalize_string(astro_name),
                "dropdown_option_id": dropdown_option_id,
                "dropdown_category": category.lower() if category else None,
                "dropdown_option_name": option_info.get("name") or _normalize_string(astro_name) or sku_tag_str,
            }
            cache.append(entry)
    except Exception as exc:  # pragma: no cover - safeguard for schema drift
        log_event(f"Failed to load SKU tag metadata: {exc}")
    _SKU_TAG_METADATA = cache
    return cache


def _category_to_spec_field(category: Optional[str]) -> Optional[str]:
    if not category:
        return None
    return _CATEGORY_TO_SPEC_FIELD.get(category.lower())


def _load_admin_sku_rules(cursor) -> List[Dict[str, Any]]:
    global _ADMIN_SKU_RULES, _ADMIN_SKU_RULES_LOADED_AT
    if (
        _ADMIN_SKU_RULES is not None
        and time.monotonic() - _ADMIN_SKU_RULES_LOADED_AT < 30
    ):
        return _ADMIN_SKU_RULES

    rules: List[Dict[str, Any]] = []
    try:
        cursor.execute(
            """
            SELECT id, category, sku_tag, detected_value, priority
            FROM sku_detection_rule
            WHERE enabled = 1
            """
        )
        for rule_id, category, sku_tag, detected_value, priority in cursor.fetchall():
            category_text = _normalize_string(category).lower()
            normalized_tag = _normalize_token(_normalize_string(sku_tag))
            detected_text = _normalize_string(detected_value)
            field = _category_to_spec_field(category_text)
            if not field or not normalized_tag or not detected_text:
                continue
            rules.append(
                {
                    "id": int(rule_id),
                    "field": field,
                    "normalized_tag": normalized_tag,
                    "detected_value": detected_text,
                    "priority": int(priority or 100),
                }
            )
    except Exception as exc:
        # Older Astro databases do not have this table yet.
        log_event(f"Administrator SKU rules unavailable; using legacy mappings: {exc}")
        rules = []

    rules.sort(
        key=lambda item: (
            item["priority"],
            -len(item["normalized_tag"]),
            item["id"],
        )
    )
    _ADMIN_SKU_RULES = rules
    _ADMIN_SKU_RULES_LOADED_AT = time.monotonic()
    return _ADMIN_SKU_RULES


def _extract_details_from_admin_rules(cursor, sku) -> Dict[str, str]:
    normalized_sku = _normalize_token(sku)
    if not normalized_sku:
        return {}
    matched: Dict[str, str] = {}
    for rule in _load_admin_sku_rules(cursor):
        if rule["normalized_tag"] in normalized_sku and rule["field"] not in matched:
            matched[rule["field"]] = rule["detected_value"]
    if "Battery" in matched:
        matched["Battery 2"] = matched["Battery"]
    return matched


def _extract_details_from_dropdown(cursor, sku) -> Optional[Dict[str, str]]:
    metadata = _load_sku_tag_metadata(cursor)
    if not metadata:
        return None
    normalized_sku = _normalize_token(sku)
    if not normalized_sku:
        return None
    matched: Dict[str, str] = {}
    matched_tags: set[str] = set()
    for entry in sorted(metadata, key=lambda item: len(item["normalized_tag"]), reverse=True):
        tag = entry["normalized_tag"]
        if not tag or tag in matched_tags:
            continue
        if tag not in normalized_sku:
            continue
        field = _category_to_spec_field(entry["dropdown_category"])
        if not field:
            continue
        value = entry["dropdown_option_name"] or entry["astro_name"] or entry["sku_tag"]
        if not value:
            continue
        if field not in matched:
            matched[field] = value
        matched_tags.add(tag)
    if not matched:
        return None
    if "Battery" in matched and "Battery 2" not in matched:
        matched["Battery 2"] = matched["Battery"]
    return matched


def _extract_details_from_sku_keywords(sku):
    # Extract hardware details from the SKU string using keywords from the config
    sku = sku or ""
    config = load_config()
    details = {
        "Model": "Unknown",
        "CPU": "Unknown",
        "SSD": "Unknown",
        "RAM": "Unknown",
        "Resolution": "Unknown",
        "Windows": "Unknown",
        "Battery": "Unknown",
    }

    def keywords(option):
        return [word.strip() for word in config.get(
            "search", option, fallback="").split(",") if word.strip()]

    CPU_KEYWORDS = keywords("cpu_keywords")
    RAM_KEYWORDS = keywords("ram_keywords")
    SSD_KEYWORDS = keywords("ssd_keywords")
    MODEL_KEYWORDS = keywords("model_keywords")
    RESOLUTION_KEYWORDS = keywords("resolution_keywords")
    WINDOWS_KEYWORDS = keywords("windows_keywords")
    GRADE_KEYWORDS = keywords("grade_keywords")

    grade_map = {
        "AGRADE": "70% Battery",
        "BGRADE": "45% Battery",
        "CGRADE": "5% Battery",
    }

    def match_with_fallback(keywords, target):
        for keyword in keywords:
            if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", target, re.IGNORECASE):
                return keyword
        for keyword in keywords:
            if keyword.lower() in target.lower():
                return keyword
        return None

    model_match = match_with_fallback(MODEL_KEYWORDS, sku)
    if model_match:
        details["Model"] = model_match

    cpu_match = match_with_fallback(CPU_KEYWORDS, sku)
    if cpu_match:
        details["CPU"] = cpu_match

    from services.storage import sku_storage

    details["SSD"] = sku_storage(sku, SSD_KEYWORDS) or "Unknown"

    ram_match = match_with_fallback(RAM_KEYWORDS, sku)
    if ram_match:
        details["RAM"] = ram_match.replace("RAM", "").replace("GB", "").strip() + "GB"

    res_match = match_with_fallback(RESOLUTION_KEYWORDS, sku)
    if res_match:
        details["Resolution"] = res_match

    win_match = match_with_fallback(WINDOWS_KEYWORDS, sku)
    if win_match:
        details["Windows"] = "Windows 11" if "11" in win_match else "Windows 10"

    for keyword in GRADE_KEYWORDS:
        if keyword.upper() in sku.upper():
            details["Battery"] = grade_map.get(keyword.upper(), "Unknown")

    details["Battery 2"] = details["Battery"]
    return details


def extract_details_from_sku(cursor, sku):
    """
    Derive hardware details from the SKU using dropdown metadata when available,
    otherwise fall back to the legacy keyword parsing.
    """
    fallback = _extract_details_from_sku_keywords(sku)
    admin_details = _extract_details_from_admin_rules(cursor, sku)
    dropdown_details = None
    try:
        dropdown_details = _extract_details_from_dropdown(cursor, sku)
    except Exception as exc:  # pragma: no cover - defensive safety
        log_event(f"SKU dropdown extraction failed: {exc}")
    if not admin_details and not dropdown_details:
        return fallback

    combined = {}
    for field, value in fallback.items():
        combined[field] = (
            admin_details.get(field)
            or (dropdown_details or {}).get(field)
            or value
        )
    combined["Battery 2"] = (
        admin_details.get("Battery 2")
        or (dropdown_details or {}).get("Battery 2")
        or fallback.get("Battery 2")
    )
    from services.storage import resolve_requirement

    combined["SSD"] = resolve_requirement(combined["SSD"], fallback.get("SSD"))
    return combined

_last_wmi_error = None


def _ensure_wmi_instance():
    """Create a client owned by the calling, COM-initialised thread."""

    if sys.platform != "win32":
        return None

    try:
        return wmi.WMI()
    except Exception as exc:  # noqa: BLE001 - log details for supportability
        _handle_wmi_error(exc)
        return None



def _handle_wmi_error(error):
    """Log WMI errors once and reset the cached client for a future retry."""

    global _last_wmi_error

    message = str(error)
    if message != _last_wmi_error:
        from services.runtime import log_diagnostic
        log_diagnostic('battery.live_read_failed', error=error, stage='wmi',
                       reason='Check Windows battery provider and COM apartment')
        _last_wmi_error = message



def _read_native_battery_state(index, expected_count):
    from services.measurements import native_battery_live_state
    provider = None
    try:
        provider = wmi.WMI(namespace=r'root\wmi')
        def rows(name, keys):
            return [{key: getattr(row, key, None) for key in keys}
                    for row in getattr(provider, name)()
                    if getattr(row, 'Active', True)]
        static = rows('BatteryStaticData', ('InstanceName', 'Capabilities'))
        full = rows('BatteryFullChargedCapacity', ('InstanceName', 'FullChargedCapacity'))
        status = rows('BatteryStatus', ('InstanceName', 'RemainingCapacity', 'Charging',
                                      'Discharging', 'PowerOnline', 'ChargeRate', 'DischargeRate'))
        return native_battery_live_state(static, full, status, index, expected_count)
    except Exception:
        # Optional provider failures must not discard the standard charge reading.
        return None
    finally:
        provider = None


def get_live_battery_state(index=0):
    result = {"state": "unreadable", "percent": None, "charging": None,
              "power_state": "Unknown", "source": "Win32_Battery live"}
    com = None
    instance, batteries, battery = None, None, None
    try:
        if sys.platform == 'win32':
            import pythoncom
            pythoncom.CoInitialize()
            com = pythoncom
        instance = _ensure_wmi_instance()
        if instance is None:
            return result
        batteries = list(instance.Win32_Battery())
        if index >= len(batteries):
            return dict(result, state="absent", power_state="Absent")
        battery = batteries[index]
        native = _read_native_battery_state(index, len(batteries))
        try:
            percent = int(battery.EstimatedChargeRemaining)
        except (TypeError, ValueError):
            percent = None
        try:
            status = int(battery.BatteryStatus)
        except (TypeError, ValueError):
            status = None
        if percent is not None and 0 <= percent <= 100:
            result.update(state="measured", percent=percent)
        names = {1: "Discharging", 2: "AC power (charging unconfirmed)",
                 3: "Fully charged", 4: "Low", 5: "Critical",
                 6: "Charging", 7: "Charging and high", 8: "Charging and low",
                 9: "Charging and critical", 11: "Partially charged"}
        result["power_state"] = names.get(status, "Unknown")
        result["charging"] = True if status in {6, 7, 8, 9} else (False if status in {1, 3, 4, 5, 11} else None)
        if native is not None:
            # Single-pack fallback percentage is unambiguous. Multiple packs use
            # their own matched remaining/full capacity rather than mixing orders.
            percent = native.get('percent')
            if percent is None and len(batteries) == 1:
                percent = result['percent']
            result.update(native, percent=percent,
                          state='measured' if percent is not None else 'unreadable')
    except Exception as exc:
        _handle_wmi_error(exc)
    finally:
        # Release proxies before leaving the COM apartment that created them.
        battery, batteries, instance = None, None, None
        if com is not None:
            com.CoUninitialize()
    return result


def get_live_battery_percent(index=0):
    return get_live_battery_state(index)["percent"]


def get_battery_bar_state():
    """Prefer pack evidence; use Windows' overall reading if WMI cannot read it.

    This fallback is only for the live display, never per-pack health/results.
    AC power alone does not establish that the battery is charging.
    """
    live = get_live_battery_state(0)
    percent = live.get('percent')
    if type(percent) in (int, float) and 0 <= percent <= 100:
        return live
    try:
        import psutil
        battery = psutil.sensors_battery()
        percent = battery.percent if battery is not None else None
        if type(percent) not in (int, float) or not 0 <= percent <= 100:
            return live
        plugged = battery.power_plugged
        power_state = ('Fully charged' if plugged is True and percent == 100
                       else 'AC power (charging unconfirmed)' if plugged is True
                       else 'Discharging' if plugged is False else 'Unknown')
        return dict(state='measured', percent=round(percent),
                    charging=None if plugged is not False and percent < 100 else False,
                    power_state=power_state, rate_watts=None,
                    rate_state='unavailable', source='Windows power status',
                    aggregate=True)
    except Exception as exc:
        from services.runtime import log_diagnostic
        log_diagnostic('battery.live_read_failed', error=exc, stage='power_status')
        return live


def is_battery_charging(index=0) -> bool:
    return get_live_battery_state(index)["charging"] is True


def preload_previous_results():
    # Load previous test results from the database for the current serial number
    from utils.specs import get_laptop_specs
    from db.database import get_db_connection
    from utils.helpers import log_event

    specs = get_laptop_specs()
    serial_number = specs.get("Serial Number", "Unknown")
    results = {}

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT test_keyboard, test_speaker, test_microphone, test_display, test_webcam, test_usb, test_wifi
            FROM order_serials
            WHERE serial_number = %s
        """, (serial_number,))
        row = cursor.fetchone()
        conn.close()

        print(f"Row from DB: {row}")  # ðŸ§ª Debug output

        if row:
            keys = ["keyboard", "speaker", "microphone", "display", "webcam", "usb", "wifi"]
            for i, result in enumerate(row):
                cleaned = result.strip().lower() if result else ""
                if cleaned in ["pass", "fail"]:
                    results[keys[i]] = cleaned
                elif cleaned in ["n/a", "na"]:
                    results[keys[i]] = "Not Run"
                elif cleaned == "":
                    results[keys[i]] = "Not Run"
                else:
                    log_event(f"Unexpected result value: {result} for {keys[i]}")
    except Exception as err:
        log_event(f"MySQL error loading test results: {err}")

    return results

def ensure_batteryinfoview(download_dir=None):
    """
    Ensure BatteryInfoView is downloaded and extracted in the specified directory.
    Returns the path to BatteryInfoView.exe.
    """
    if download_dir is None:
        bundled_root = (Path(sys._MEIPASS) if getattr(sys, "frozen", False)
                        else Path(__file__).resolve().parents[1])
        roots = [bundled_root, Path(get_app_dir())]
        for root in roots:
            bundled = root / "assets" / "BatteryInfoView" / "BatteryInfoView.exe"
            if bundled.is_file():
                return str(bundled.resolve())
        download_dir = str(Path(get_app_dir()) / "assets" / "BatteryInfoView")
    elif not Path(download_dir).is_absolute():
        download_dir = str(Path(get_app_dir()) / download_dir)
    url = "https://www.nirsoft.net/utils/batteryinfoview-x64.zip"
    zip_name = "batteryinfoview-x64.zip"
    exe_name = "BatteryInfoView.exe"
    os.makedirs(download_dir, exist_ok=True)
    exe_path = os.path.join(download_dir, exe_name)
    zip_path = os.path.join(download_dir, zip_name)

    # Check if already extracted
    if os.path.exists(exe_path):
        return exe_path

    # Download if not present
    if not os.path.exists(zip_path):
        try:
            print(f"Downloading {url}...")
            with urllib.request.urlopen(url, timeout=30) as response:
                with open(zip_path, "wb") as target:
                    while True:
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        target.write(chunk)
        except Exception as err:
            log_event(f"Failed to download BatteryInfoView: {err}")
            raise

    expected_hash = os.getenv("BATTERYINFOVIEW_SHA256")
    if expected_hash:
        sha256 = hashlib.sha256()
        with open(zip_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        file_hash = sha256.hexdigest()
        if file_hash.lower() != expected_hash.lower():
            log_event(
                f"BatteryInfoView checksum mismatch: expected {expected_hash}, got {file_hash}"
            )
            os.remove(zip_path)
            raise ValueError("BatteryInfoView checksum mismatch")
    else:
        log_event("BATTERYINFOVIEW_SHA256 not set; skipping checksum verification")

    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(download_dir)
    except Exception as err:
        log_event(f"Failed to extract BatteryInfoView: {err}")
        raise
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)

    if not os.path.exists(exe_path):
        raise FileNotFoundError(f"{exe_name} not found after extraction.")

    return exe_path
