"""Regressions for the 28 October physical bench findings."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from services.hardware_job import HardwareJob
from utils import helpers
from update_service import parse_manifest
from services.update_integrity import UpdateError
import main_logic


class RecentRunFixTests(unittest.TestCase):
    def test_camera_preview_continues_while_new_frames_arrive_then_stall_times_out(self):
        with TemporaryDirectory() as directory:
            job = HardwareJob.__new__(HardwareJob)
            job.directory = Path(directory)
            job.closed = False
            job.kind = 'camera'
            job.awaiting_startup = True
            job.deadline = 130
            job.max_result_bytes = None
            job._blocked_reads = {}
            job.close = Mock()
            job.process = Mock()
            job.process.poll.return_value = None
            for second in range(100, 181):
                (job.directory / 'result.json').write_text(json.dumps({
                    'state': 'preview', 'frames_seen': second,
                    'heartbeat': second, 'camera_index': 0}))
                with patch('services.hardware_job.time.monotonic', return_value=second), \
                        patch('services.hardware_job.time.time', return_value=second):
                    self.assertEqual(job.poll()['state'], 'preview')
            self.assertFalse(job.awaiting_startup)
            self.assertEqual(job.deadline, 185)
            with patch('services.hardware_job.time.monotonic', return_value=184), \
                    patch('services.hardware_job.time.time', return_value=184):
                job.poll()
                self.assertEqual(job.deadline, 185)  # Same frame cannot renew the lease.
            with patch('services.hardware_job.time.monotonic', return_value=186):
                with self.assertRaises(TimeoutError):
                    job.poll()
            job.close.assert_called_once()

    def test_battery_com_clients_never_cross_threads_and_are_balanced(self):
        import pythoncom
        local = threading.local()
        barrier = threading.Barrier(2)
        calls = []
        def initialise():
            local.active = True
        def uninitialise():
            self.assertTrue(local.active)
            local.active = False
            calls.append(threading.get_ident())
        def create():
            self.assertTrue(local.active)
            owner = threading.get_ident()
            barrier.wait(timeout=5)
            def read():
                self.assertEqual(threading.get_ident(), owner)
                self.assertTrue(local.active)
                return [SimpleNamespace(EstimatedChargeRemaining=79, BatteryStatus=1)]
            return SimpleNamespace(Win32_Battery=read)
        with patch.object(pythoncom, 'CoInitialize', side_effect=initialise), \
                patch.object(pythoncom, 'CoUninitialize', side_effect=uninitialise), \
                patch.object(helpers.wmi, 'WMI', side_effect=create):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: helpers.get_live_battery_state(), range(2)))
        self.assertEqual([result['percent'] for result in results], [79, 79])
        self.assertEqual(len(set(calls)), 2)

    def test_explicit_alias_lists_and_generic_windows_match_without_loose_models(self):
        for field, expected, actual in (
            ('Model', 'T480s Notebook PC, THINKPAD T480S', 'T480s'),
            ('CPU', 'i5-520M, i5-8250U, i5-8265U', 'Intel Core i5-8250U CPU @ 1.60GHz'),
            ('Windows', 'Windows 11', 'Windows 11 Pro'),
        ):
            self.assertTrue(helpers.specification_matches(field, expected, actual))
        for field, expected, actual in (
            ('Model', 'T480', 'T480s'), ('Model', 'T480s', 'T480'),
            ('CPU', 'i5-8250U', 'i5-8265U'),
            ('Windows', 'Windows 11 Pro', 'Windows 11 Home'),
            ('Windows', 'Windows 10', 'Windows 11 Pro'),
        ):
            self.assertFalse(helpers.specification_matches(field, expected, actual))
        with patch.object(main_logic, 'get_live_battery_state', return_value={
                'percent': 79, 'power_state': 'Discharging'}):
            text = main_logic.build_results_footer(
                {'Model': 'T480s', 'CPU': 'i5-8250U', 'Windows': 'Windows 11 Pro'},
                {'Model': 'T480s Notebook PC, THINKPAD T480S',
                 'CPU': 'i5-520M, i5-8250U', 'Windows': 'Windows 11'}, {})[0]
        self.assertNotIn('Model:', text)
        self.assertNotIn('CPU:', text)
        self.assertNotIn('Windows:', text)

    def test_release_repository_case_is_accepted_but_other_repos_and_assets_are_not(self):
        root = 'https://github.com/LewisJ14/SecondChecking/releases/'
        manifest = dict(version='0.1.38', release_page=root + 'tag/v0.1.38',
                        download_url=root + 'download/v0.1.38/SecondChecking-0.1.38.exe')
        self.assertEqual(parse_manifest(manifest).version, '0.1.38')
        for value in (root.replace('LewisJ14', 'other') + 'tag/v0.1.38',
                      root + 'tag/v0.1.39'):
            with self.assertRaises(UpdateError):
                parse_manifest(dict(manifest, release_page=value))
        with self.assertRaises(UpdateError):
            parse_manifest(dict(manifest, download_url=manifest['download_url'].replace('.exe', '.EXE')))


if __name__ == '__main__':
    unittest.main()
