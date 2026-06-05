# hardwaretests/wifi.py
import subprocess

from utils.helpers import log_event


def check_wifi_available() -> tuple[bool, str]:
    """Return whether Windows can see an available Wi-Fi adapter."""

    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "drivers"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as exc:
        return False, f"Wi-Fi check failed to run: {exc}"

    output = f"{result.stdout}\n{result.stderr}".strip()
    lowered = output.lower()

    if result.returncode != 0:
        return False, output or f"netsh exited with code {result.returncode}"
    if "wireless autoconfig service" in lowered and "not running" in lowered:
        return False, "Wireless AutoConfig service is not running."
    if "there is no wireless interface" in lowered:
        return False, "No wireless interface was found."
    if "interface name" in lowered or "driver" in lowered:
        return True, "Wi-Fi adapter detected."

    return False, output or "No Wi-Fi adapter details were returned."


def run_wifi_test(root, test_results, test_labels, tests_window=None, completion_event=None):
    passed, detail = check_wifi_available()
    result = "pass" if passed else "fail"
    test_results["wifi"] = result
    log_event(f"Wi-Fi automatic hardware test {result}: {detail}")

    if tests_window:
        tests_window.update_icon("wifi")
        tests_window.update_status(detail)
    elif "wifi_label" in test_labels:
        test_labels["wifi_label"].config(text="OK" if passed else "X")

    if completion_event:
        completion_event.set()
