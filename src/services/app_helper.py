"""Bounded application helpers with file IPC for windowed executables."""
import json
from pathlib import Path
import subprocess
import time
from uuid import UUID, uuid4

from services.hardware_job import HardwareJob, WorkerResultTooLarge, write_ready, write_result
from services.mdm_evidence import LOCAL_STATES, SOURCE
from services.runtime import log_diagnostic, exception_report

KINDS = {"updates", "mdm", "windows-update"}
MAX_RESULT_BYTES = 2 * 1024 * 1024


class HelperError(RuntimeError):
    pass


def update_payload():
    from update_service import UpdateService
    service = UpdateService()
    manifest = service.check_for_updates()
    if manifest is None:
        return {"update_check_version": 1, "state": "up_to_date",
                "current_version": service.current_version}
    return {"update_check_version": 1, "state": "update_available",
            "version": manifest.version, "download_url": manifest.download_url,
            "release_page": manifest.release_page, "notes": manifest.notes,
            "metadata": manifest.metadata,
            "sha256": getattr(manifest, "sha256", None),
            "size": getattr(manifest, "size", None),
            "signer_sha256": getattr(manifest, "signer_sha256", None)}


def mdm_payload():
    from utils.helpers import refresh_mdm_lock_status
    return refresh_mdm_lock_status()


def validate_payload(kind, payload):
    if not isinstance(payload, dict):
        raise HelperError("Helper returned an invalid payload.")
    if kind == "updates":
        from services.update_result import decode_update_result
        from version import __version__
        decode_update_result(json.dumps(payload), __version__)
        if payload.get("update_check_version") != 1:
            raise HelperError("Helper returned an unsupported update result.")
    elif kind == "windows-update":
        if payload.get("state") != "completed":
            raise HelperError("Windows Update did not confirm completion.")
    elif (payload.get("evidence_version") != 1
          or payload.get("state") not in LOCAL_STATES
          or payload.get("source") != SOURCE
          or payload.get("tenant_verification") != "not_checked"):
        raise HelperError("Helper returned unqualified local MDM evidence.")
    return payload


def run_worker(directory):
    directory = Path(directory)
    request_id, kind = None, None
    try:
        request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
        kind = request["kind"]
        request_id = str(UUID(request["arguments"]["request_id"]))
        if kind not in KINDS:
            raise ValueError("Unsupported helper.")
        write_ready(directory, kind)
        if kind == "updates":
            payload = update_payload()
        elif kind == "mdm":
            payload = mdm_payload()
        else:
            from services.maintenance import run_windows_updates
            run_windows_updates()
            payload = {"state": "completed"}
        validate_payload(kind, payload)
        reply = {"helper_version": 1, "request_id": request_id, "kind": kind,
                 "outcome": "ok", "payload": payload}
    except Exception as exc:
        log_diagnostic('helper.failed', error=exc, kind=kind,
                       request_id=(request_id or '').replace('-', ''))
        reply = {"helper_version": 1, "request_id": request_id, "kind": kind,
                 "outcome": "error", "error": "Helper operation failed.",
                 "diagnostic": exception_report(exc)}
        if kind == 'updates':
            from services.update_integrity import UpdateCheckError, UpdateError
            reply['error_code'] = (exc.reason if isinstance(exc, UpdateCheckError)
                                   else 'invalid_release' if isinstance(exc, UpdateError)
                                   else 'unavailable')
    write_result(directory, reply)


def decode_reply(reply, kind, request_id):
    if (not isinstance(reply, dict) or reply.get("helper_version") != 1
            or reply.get("request_id") != request_id or reply.get("kind") != kind):
        raise HelperError("Helper result is missing, unsupported or mismatched.")
    if reply.get("outcome") != "ok":
        if kind == 'updates':
            from services.update_integrity import CHECK_FAILURES
            code = reply.get('error_code')
            if isinstance(code, str) and code in CHECK_FAILURES:
                raise HelperError(CHECK_FAILURES[code])
        raise HelperError("Helper operation failed; no result was confirmed. "
                          "See helper.failed in logs.txt (reference {}).".format(
                              request_id.replace('-', '')))
    return validate_payload(kind, reply.get("payload"))


class AppHelperJob(HardwareJob):
    max_result_bytes = MAX_RESULT_BYTES

    def __init__(self, kind, timeout=60):
        if kind not in KINDS:
            raise ValueError("Unsupported application helper.")
        self.kind = kind
        self.request_id = str(uuid4())
        super().__init__(kind, arguments={"request_id": self.request_id},
                         timeout=timeout, worker_flag="--app-helper")

    def poll(self):
        try:
            reply = super().poll()
        except WorkerResultTooLarge as exc:
            raise HelperError(str(exc)) from None
        if reply is None:
            return None
        return decode_reply(reply, self.kind, self.request_id)


def run_helper(kind, timeout=60):
    job = AppHelperJob(kind, timeout)
    try:
        while True:
            reply = job.poll()
            if reply is not None:
                try:
                    exit_code = job.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    raise HelperError("Helper did not exit after reporting its result.") from None
                if exit_code != 0:
                    raise HelperError("Helper exited unsuccessfully; result was not accepted.")
                return reply
            time.sleep(.03)
    finally:
        job.close()
