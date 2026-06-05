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
from typing import Any, Dict, List, Optional, Set
import requests

SYSROOT = Path(os.environ.get("WINDIR", r"C:\Windows"))
DSREGCMD_PATH = SYSROOT / "System32" / "dsregcmd.exe"
GPUPDATE_PATH = SYSROOT / "System32" / "gpupdate.exe"
HARDCODED_SECOND_CHECK_KEY = "n_wHG3XvhznRp-bXm6tpN4OO_E4mnwu11XxkbVEStMv7W5fpjl1saGb8Ks7NWA-i"

_SKU_TAG_METADATA: Optional[List[Dict[str, Any]]] = None
_DROPDOWN_OPTION_CACHE: Optional[Dict[int, Dict[str, str]]] = None
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

    config_base_url = ""
    config_api_key = ""
    try:
        config = load_config()
        if config.has_section("webtools"):
            config_base_url = config.get("webtools", "base_url", fallback="").strip()
            config_api_key = config.get("webtools", "second_check_key", fallback="").strip()
    except Exception as exc:
        log_event(f"Hash upload config read warning: {exc}")

    base_url = (
        os.getenv("SECOND_CHECK_BASE_URL", "").strip()
        or config_base_url
        or "http://192.168.1.188:5001"
    )
    api_key = (
        os.getenv("SECOND_CHECK_KEY", "").strip()
        or HARDCODED_SECOND_CHECK_KEY
        or config_api_key
    )
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
    max_attempts = 4
    backoff_seconds = 1

    for attempt in range(1, max_attempts + 1):
        try:
            with open(file_path, "rb") as csv_handle:
                response = requests.post(
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
        body = (response.text or "").strip().replace("\n", " ")
        if len(body) > 200:
            body = f"{body[:200]}..."
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
            log_event(f"Hash upload failed {identifier_text} file={file_name} status=400 payload/format issue {body}")
            return False
        if status == 401:
            log_event(f"Hash upload failed {identifier_text} file={file_name} status=401 auth issue")
            return False
        if status == 404:
            log_event(f"Hash upload failed {identifier_text} file={file_name} status=404 serial not found")
            return False
        if status >= 500:
            log_event(f"Hash upload failed {identifier_text} file={file_name} status={status} server error {body}")
            return False

        log_event(f"Hash upload failed {identifier_text} file={file_name} status={status} {body}")
        return False

    log_event(f"Hash upload failed {identifier_text} file={file_name} retries exhausted")
    return False

def log_event(message):
    log_path = get_log_path()
    try:
        # Log rotation: if log file > 5MB, rotate
        if os.path.exists(log_path) and os.path.getsize(log_path) > 5 * 1024 * 1024:
            if os.path.exists(log_path + ".1"):
                os.remove(log_path + ".1")
            os.rename(log_path, log_path + ".1")
        # Append the log message with a timestamp
        with open(log_path, "a", encoding="utf-8") as log_file:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_file.write(f"[{timestamp}] {message}\n")
    except Exception as e:
        print(f"Failed to log event: {e}")

def get_config_path():
    # Determine the path to the configuration file
    return os.path.join(get_app_dir(), "config.ini")


def get_log_path():
    return os.path.join(get_app_dir(), "logs.txt")


def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.abspath(os.path.dirname(sys.executable))
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def load_config():
    log_event("Loading configuration file...")
    config = configparser.ConfigParser()
    try:
        config.read(get_config_path())
        log_event("Configuration file loaded successfully.")
    except Exception as e:
        log_event(f"Error loading configuration file: {e}")
        raise
    return config

def parse_percent(text):
    if text is None:
        return None
    try:
        # Extract a percentage value from the given text
        match = re.search(r"-?\d+(\.\d+)?", text)
        if match:
            return int(float(match.group()))
    except Exception as e:
        log_event(f"parse_percent error: {e} for input: {text}")
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


def check_mdm_lock_status() -> Dict[str, str]:
    """Inspect Autopilot registry values to determine Microsoft MDM lock status."""

    if sys.platform != "win32":
        message = "Microsoft MDM lock checks are only available on Windows."
        log_event(message)
        return {"state": "unsupported", "details": message}

    import winreg  # type: ignore[import]

    autopilot_key_path = r"SOFTWARE\Microsoft\Provisioning\Diagnostics\Autopilot"

    try:
        autopilot_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, autopilot_key_path)
    except FileNotFoundError:
        message = "Autopilot diagnostics registry key not found; device is likely not MDM locked."
        log_event(message)
        return {"state": "not_locked", "details": message}
    except OSError as exc:
        message = f"Failed to open Autopilot diagnostics registry key: {exc}"
        log_event(message)
        return {"state": "error", "details": message}

    def _query_value(key, value_name):
        try:
            value, _ = winreg.QueryValueEx(key, value_name)
            return value
        except FileNotFoundError:
            return None
        except OSError as exc:
            log_event(f"Error reading Autopilot registry value '{value_name}': {exc}")
            return None

    tenant_id = _query_value(autopilot_key, "CloudAssignedTenantId")
    tenant_domain = _query_value(autopilot_key, "CloudAssignedTenantDomain")

    entdm_id = None
    ztd_id = None
    try:
        correlations_key = winreg.OpenKey(autopilot_key, "EstablishedCorrelations")
    except FileNotFoundError:
        correlations_key = None
    except OSError as exc:
        log_event(f"Unable to open EstablishedCorrelations subkey: {exc}")
        correlations_key = None

    if correlations_key is not None:
        entdm_id = _query_value(correlations_key, "EntDMID")
        ztd_id = _query_value(correlations_key, "ZTDRegistrationID")
        winreg.CloseKey(correlations_key)

    winreg.CloseKey(autopilot_key)

    details_parts = []
    if tenant_id:
        details_parts.append(f"Tenant ID: {tenant_id}")
    if tenant_domain:
        details_parts.append(f"Tenant Domain: {tenant_domain}")
    if entdm_id:
        details_parts.append(f"EntDMID: {entdm_id}")
    if ztd_id:
        details_parts.append(f"ZTDID: {ztd_id}")

    if tenant_id:
        detail_text = " | ".join(details_parts) if details_parts else "Autopilot profile detected."
        log_event(f"Microsoft MDM lock detected: {detail_text}")
        return {"state": "locked", "details": detail_text}

    detail_text = "No Autopilot tenant information was found." if not details_parts else " | ".join(details_parts)
    log_event("Microsoft MDM lock not detected.")
    return {"state": "not_locked", "details": detail_text}


def refresh_mdm_lock_status() -> Dict[str, str]:
    """Run policy refresh commands and return the latest lock status."""

    success = run_mdm_policy_commands()
    if success:
        log_event("MDM policy commands completed before rechecking lock status.")
    else:
        log_event("MDM policy commands failed or were skipped; reading lock status anyway.")
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
    sku_token = _normalize_token(sku_spec)
    laptop_token = _normalize_token(laptop_spec)
    if not sku_token or not laptop_token:
        return False
    if sku_token == laptop_token:
        return True
    if is_generic_cpu_spec(sku_spec):
        return sku_token in laptop_token
    return False


def _storage_capacity_to_gb(value: Optional[str]) -> Optional[int]:
    text = _normalize_string(value)
    if not text:
        return None
    match = _STORAGE_PATTERN.search(text)
    if not match:
        return None
    try:
        amount = float(match.group(1))
    except (TypeError, ValueError):
        return None
    unit = (match.group(2) or "").upper()
    if unit == "TB":
        amount *= 1024.0
    return int(round(amount))


def storage_specs_are_compatible(sku_spec: Optional[str], laptop_spec: Optional[str]) -> bool:
    """Treat equivalent storage capacities as a match (e.g. 1024GB == 1TB)."""
    sku_gb = _storage_capacity_to_gb(sku_spec)
    laptop_gb = _storage_capacity_to_gb(laptop_spec)
    if sku_gb is not None and laptop_gb is not None:
        return abs(sku_gb - laptop_gb) <= 1
    sku_token = _normalize_token(sku_spec)
    laptop_token = _normalize_token(laptop_spec)
    return bool(sku_token and laptop_token and sku_token == laptop_token)


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

    CPU_KEYWORDS = config.get("search", "cpu_keywords").split(",")
    RAM_KEYWORDS = config.get("search", "ram_keywords").split(",")
    SSD_KEYWORDS = config.get("search", "ssd_keywords").split(",")
    MODEL_KEYWORDS = config.get("search", "model_keywords").split(",")
    RESOLUTION_KEYWORDS = config.get("search", "resolution_keywords").split(",")
    WINDOWS_KEYWORDS = config.get("search", "windows_keywords").split(",")
    GRADE_KEYWORDS = config.get("search", "grade_keywords").split(",")

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

    ssd_match = match_with_fallback(SSD_KEYWORDS, sku)
    if ssd_match:
        if "TB" in ssd_match.upper():
            details["SSD"] = ssd_match.replace("SSD", "").strip()
        else:
            details["SSD"] = ssd_match.replace("SSD", "").strip() + "GB"

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
    dropdown_details = None
    try:
        dropdown_details = _extract_details_from_dropdown(cursor, sku)
    except Exception as exc:  # pragma: no cover - defensive safety
        log_event(f"SKU dropdown extraction failed: {exc}")
    if not dropdown_details:
        return fallback

    combined = {}
    for field, value in fallback.items():
        combined[field] = dropdown_details.get(field) or value
    combined["Battery 2"] = dropdown_details.get("Battery 2") or fallback.get("Battery 2")
    return combined

_wmi_instance = None  # Cache WMI instance
_last_wmi_error = None


def _ensure_wmi_instance():
    """Return a cached WMI instance, initialising when required."""

    global _wmi_instance

    if sys.platform != "win32":
        return None

    if _wmi_instance is not None:
        return _wmi_instance

    try:
        try:
            import pythoncom  # type: ignore[import]

            pythoncom.CoInitialize()
        except ImportError:
            # pywin32 may not be installed when running unit tests on non-Windows platforms.
            pass
        _wmi_instance = wmi.WMI()
    except Exception as exc:  # noqa: BLE001 - log details for supportability
        _handle_wmi_error(exc)
        return None

    return _wmi_instance


def _handle_wmi_error(error):
    """Log WMI errors once and reset the cached client for a future retry."""

    global _wmi_instance, _last_wmi_error

    message = str(error)
    if message != _last_wmi_error:
        log_event(f"get_live_battery_percent error: {error}")
        _last_wmi_error = message

    _wmi_instance = None


def get_live_battery_percent(index=0):
    instance = _ensure_wmi_instance()
    if instance is None:
        return None

    try:
        batteries = instance.Win32_Battery()
        if index < len(batteries):
            return int(batteries[index].EstimatedChargeRemaining)
    except Exception as exc:  # noqa: BLE001 - surface diagnostic info
        _handle_wmi_error(exc)
    return None


def is_battery_charging(index=0) -> bool:
    """Return True if the indexed battery is actively charging."""

    instance = _ensure_wmi_instance()
    if instance is None:
        return False

    try:
        batteries = instance.Win32_Battery()
        if index < len(batteries):
            return batteries[index].BatteryStatus in {2, 6}  # Charging states
    except Exception as exc:  # noqa: BLE001 - surface diagnostic info
        _handle_wmi_error(exc)
    return False

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

        print(f"Row from DB: {row}")  # 🧪 Debug output

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

def ensure_batteryinfoview(download_dir="assets/BatteryInfoView"):
    """
    Ensure BatteryInfoView is downloaded and extracted in the specified directory.
    Returns the path to BatteryInfoView.exe.
    """
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
            urllib.request.urlretrieve(url, zip_path)
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
