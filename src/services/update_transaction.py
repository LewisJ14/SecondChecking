"""Durable executable replacement with retained backup and confirmed restart."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import time
from uuid import UUID

from services.update_integrity import (UpdateError, file_hash, signer_pin,
                                       verify_content, verify_publisher, version_tuple)


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(path))


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 65536:
        raise UpdateError("Update journal exceeds its size limit.")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise UpdateError("Invalid update journal.")
    return value


def load_plan(path):
    path = Path(path).resolve()
    plan = read_json(path)
    directory = path.parent
    if (path.name != "plan.json" or directory.parent.name != ".secondchecking-updates"
            or str(UUID(plan.get("id", ""))) != directory.name
            or plan.get("plan_version") != 1):
        raise UpdateError("Update journal is outside its owned transaction directory.")
    name = plan.get("target_name")
    if not isinstance(name, str) or Path(name).name != name or ":" in name or not name.lower().endswith(".exe"):
        raise UpdateError("Invalid update target.")
    target = directory.parent.parent / name
    if target.is_symlink() or directory.is_symlink():
        raise UpdateError("Update paths must be regular local files.")
    if version_tuple(plan["version"]) <= version_tuple(plan["from_version"]):
        raise UpdateError("Update journal does not describe a newer version.")
    return plan, directory, target


def set_state(directory, plan, state, reason=None):
    import psutil
    write_json(directory / "state.json", {
        "transaction_id": plan["id"], "state": state,
        "version": plan["version"], "from_version": plan["from_version"],
        "reason": reason, "worker_pid": os.getpid(),
        "worker_started": psutil.Process().create_time()})


def backup_path(target, identifier):
    return target.with_name("." + target.name + "." + identifier + ".previous")


def copy_atomic(source, destination, expected):
    destination = Path(destination)
    partial = destination.with_name(destination.name + ".part")
    try:
        if partial.exists() or partial.is_symlink():
            partial.unlink()
        with Path(source).open("rb") as incoming, partial.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if file_hash(partial) != expected:
            raise UpdateError("Staged executable changed during copying.")
        os.replace(str(partial), str(destination))
    finally:
        if partial.exists():
            partial.unlink()


@contextmanager
def target_lock(target):
    import msvcrt
    path = target.with_name("." + target.name + ".update.lock")
    with path.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise UpdateError("Another update or recovery is already running.") from None
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def apply_plan(path, restore=False, verifier=None, health=None, launcher=None):
    from services.update_process import check_health, launch_confirmed
    verifier = verifier or verify_publisher
    health = health or check_health
    launcher = launcher or launch_confirmed
    plan, directory, target = load_plan(path)
    backup = backup_path(target, plan["id"])
    staged = target.with_name("." + target.name + "." + plan["id"] + ".new")
    pin = signer_pin()
    if not pin or pin != plan["signer_sha256"]:
        raise UpdateError("The configured publisher does not match this update.")
    original = plan["original_sha256"]
    current = file_hash(target) if target.exists() else None
    if current not in (original, plan["sha256"], None):
        raise UpdateError("The installed executable changed; automatic recovery was stopped.")
    if restore:
        verify_content(backup, original, plan["original_size"])
        verifier(backup, pin)
        copy_atomic(backup, staged, original)
        os.replace(str(staged), str(target))
        health(target, plan["from_version"])
        set_state(directory, plan, "rolled_back", "requested_recovery")
        try:
            launcher(target, path, plan["from_version"])
        except Exception:
            set_state(directory, plan, "rollback_restart_failed", "open_previous_version_manually")
        return "rolled_back"
    if current != original:
        # Interrupted replacement is recovered to the retained original, not replayed.
        return apply_plan(path, restore=True, verifier=verifier, health=health, launcher=launcher)
    try:
        candidate = directory / "candidate.exe"
        verify_content(candidate, plan["sha256"], plan["size"])
        verifier(candidate, pin)
        health(candidate, plan["version"])
        if backup.exists():
            verify_content(backup, original, plan["original_size"])
        else:
            copy_atomic(target, backup, original)
        verifier(backup, pin)
        copy_atomic(candidate, staged, plan["sha256"])
        verify_content(staged, plan["sha256"], plan["size"])
        verifier(staged, pin)
        set_state(directory, plan, "installing")
        os.replace(str(staged), str(target))
        verify_content(target, plan["sha256"], plan["size"])
        verifier(target, pin)
        health(target, plan["version"])
        set_state(directory, plan, "restarting")
        launcher(target, path, plan["version"])
        set_state(directory, plan, "installed")
        return "installed"
    except Exception:
        if staged.exists():
            staged.unlink()
        current = file_hash(target) if target.exists() else None
        if current == original:
            set_state(directory, plan, "failed_retained", "installed_copy_retained")
        elif current in (plan["sha256"], None):
            try:
                verify_content(backup, original, plan["original_size"])
                verifier(backup, pin)
                copy_atomic(backup, staged, original)
                os.replace(str(staged), str(target))
                set_state(directory, plan, "rolled_back", "replacement_or_restart_failed")
            except Exception:
                set_state(directory, plan, "recovery_required", "retained_backup_needs_recovery")
                raise UpdateError("Update failed; use the retained previous executable for recovery.") from None
        else:
            set_state(directory, plan, "recovery_required", "installed_file_changed")
            raise UpdateError("Installed file changed; the previous backup remains available.") from None
        try:
            launcher(target, path, plan["from_version"])
        except Exception:
            set_state(directory, plan, "rollback_restart_failed", "open_previous_version_manually")
        return read_json(directory / "state.json")["state"]


def is_cancelled(directory, launch_id):
    try:
        return read_json(directory / "cancel.json").get("launch_id") == launch_id
    except (OSError, ValueError):
        return False


def wait_for_parent(directory, launch, timeout=120):
    import psutil
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_cancelled(directory, launch["launch_id"]):
            raise UpdateError("Update handoff was cancelled.")
        try:
            parent = psutil.Process(launch["parent_pid"])
            same = abs(parent.create_time() - launch["parent_started"]) < .01
            if not same or not parent.is_running():
                return
        except psutil.NoSuchProcess:
            return
        time.sleep(.1)
    raise UpdateError("The running application did not close; installed copy retained.")


def worker(path, restore=False):
    import sys
    from version import __version__
    try:
        plan, directory, target = load_plan(path)
    except Exception:
        return 1
    try:
        if (Path(sys.executable).resolve() != directory / "updater.exe"
                or plan["from_version"] != __version__):
            raise UpdateError("Update worker identity does not match the installed baseline.")
        verify_content(sys.executable, plan["original_sha256"], plan["original_size"])
        verify_publisher(sys.executable, signer_pin())
        launch = read_json(directory / "launch.json")
        with target_lock(target):
            write_json(directory / "handoff.json", {"launch_id": launch["launch_id"], "ready": True})
            wait_for_parent(directory, launch)
            if is_cancelled(directory, launch["launch_id"]):
                raise UpdateError("Update handoff cancelled.")
            apply_plan(path, restore=restore)
    except Exception:
        try:
            state = read_json(directory / "state.json").get("state")
        except (OSError, ValueError):
            state = None
        if state not in {"recovery_required", "rollback_restart_failed", "rolled_back", "failed_retained"}:
            set_state(directory, plan, "blocked", "worker_validation_or_handoff_failed")
        return 1
    return 0


def confirm_startup(path):
    import sys
    from version import __version__
    plan, directory, target = load_plan(path)
    if Path(sys.executable).resolve() != target.resolve():
        raise UpdateError("Startup confirmation came from the wrong executable.")
    write_json(directory / "startup.json", {
        "startup_version": 1, "nonce": plan["id"], "version": __version__})


def previous_plan(target):
    target = Path(target).resolve()
    root = target.parent / ".secondchecking-updates"
    if not root.is_dir():
        return None
    for directory in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:100]:
        try:
            path = directory / "plan.json"
            plan, _, owned_target = load_plan(path)
            if owned_target == target and backup_path(target, plan["id"]).is_file():
                return path
        except (OSError, ValueError, KeyError):
            continue
    return None
