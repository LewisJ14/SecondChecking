"""Device/order-scoped drafts, separate from confirmed server reports."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from services.check_results import STATES, TEST_KEYS, normalise


def result_state(results):
    state = {key: normalise(results.get(key)) for key in TEST_KEYS}
    for key, default in (("_overrides", {}), ("_coverage", {}), ("_history_unknown", []),
                         ("_provenance_unknown", False)):
        state[key] = deepcopy(results.get(key, default))
    return state


class CheckDraftStore:
    def __init__(self, directory=None):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local/share")
        self.directory = Path(directory) if directory else (
            Path(base) / "SecondChecking" / "check-drafts")

    def _path(self, key):
        digest = hashlib.sha256(json.dumps(key).encode("utf-8")).hexdigest()
        return self.directory / (digest + ".json")

    def load(self, key):
        path = self._path(key)
        if not path.exists():
            return None
        saved = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(saved, dict) or saved.get("key") != list(key)
                or not isinstance(saved.get("results"), dict)
                or not isinstance(saved.get("baseline"), dict)):
            raise ValueError("Invalid local check draft. The file was preserved.")
        for state in (saved["results"], saved["baseline"]):
            if (any(not isinstance(state.get(name), str)
                    or state[name] not in STATES for name in TEST_KEYS)
                    or not isinstance(state.get("_overrides"), dict)
                    or not isinstance(state.get("_history_unknown"), list)
                    or not isinstance(state.get("_provenance_unknown"), bool)):
                raise ValueError("Invalid local check draft results. The file was preserved.")
        return saved

    def save(self, key, results, baseline):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(key)
        temporary = path.with_suffix("." + uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps({
                "key": list(key), "results": result_state(results),
                "baseline": result_state(baseline),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }), encoding="utf-8")
            os.replace(str(temporary), str(path))
        finally:
            if temporary.exists():
                temporary.unlink()

    def discard(self, key):
        path = self._path(key)
        if path.exists():
            path.unlink()


class CheckSession:
    def __init__(self, store=None):
        self.store = store or CheckDraftStore()
        self.key = None
        self.order_number = None
        self.baseline = result_state({})

    @staticmethod
    def key_for(order_id, serial):
        serial = str(serial or "").strip()
        if not serial or serial.lower() == "unknown":
            raise ValueError("A device serial is required for a check session.")
        return int(order_id), serial

    def preserve(self, results):
        if self.key is not None:
            if result_state(results) != self.baseline:
                self.store.save(self.key, results, self.baseline)
            else:
                self.store.discard(self.key)

    def candidate(self, order_id, serial, saved_results):
        key = self.key_for(order_id, serial)
        draft = self.store.load(key)
        if draft is None and order_id:
            # Checks made before order lookup belong only to this device.
            draft = self.store.load(self.key_for(0, serial))
        conflict = bool(draft and draft["key"][0] != 0
                        and draft["baseline"] != result_state(saved_results))
        return draft, conflict

    def activate(self, order_id, order_number, serial, saved_results,
                 draft=None):
        key = self.key_for(order_id, serial)
        results = deepcopy(draft["results"] if draft else saved_results)
        baseline = result_state(saved_results)
        # Persist a restored/transferred draft before replacing its source.
        if result_state(results) != baseline:
            self.store.save(key, results, baseline)
        elif draft:
            self.store.discard(key)
        if draft and tuple(draft["key"]) != key:
            self.store.discard(tuple(draft["key"]))
        self.key, self.order_number, self.baseline = key, order_number, baseline
        return results

    def confirmed(self, order_id, serial, results):
        key = self.key_for(order_id, serial)
        self.store.discard(key)
        if key == self.key:
            self.baseline = result_state(results)
