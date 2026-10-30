"""Live rates use matched battery identities and documented milliwatt units."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from services.measurements import native_battery_live_state, battery_power_label
from utils import helpers
import psutil
import json
import tempfile


class BatteryRateTests(unittest.TestCase):
    def setUp(self):
        import pythoncom
        for name in ('CoInitialize', 'CoUninitialize'):
            boundary = patch.object(pythoncom, name)
            boundary.start()
            self.addCleanup(boundary.stop)
        self.static = [dict(InstanceName='A', Capabilities=0)]
        self.full = [dict(InstanceName='a', FullChargedCapacity=50000)]
        self.status = [dict(InstanceName='A', Charging=True, Discharging=False,
                            PowerOnline=True, RemainingCapacity=45000,
                            ChargeRate=18400, DischargeRate=0)]

    def read(self):
        return native_battery_live_state(self.static, self.full, self.status, expected_count=1)

    def test_charging_discharge_and_zero_rate(self):
        state = self.read()
        self.assertEqual(state['percent'], 90)
        self.assertEqual(battery_power_label(state), 'Charging — 18.4 W')
        # AC can be connected while the battery is still discharging.
        self.status[0].update(Charging=False, Discharging=True, DischargeRate=7600)
        self.assertEqual(battery_power_label(self.read()), 'Discharging — 7.6 W')
        self.status[0].update(Discharging=False, ChargeRate=0, DischargeRate=0)
        self.assertEqual(battery_power_label(self.read()), 'Not charging — 0.0 W')
        self.assertFalse(self.read()['charging'])

    def test_missing_sentinel_invalid_and_relative_rates_never_become_watts(self):
        for value in (None, -1, -2147483648, 0x80000000, 0xffffffff, True, '18400'):
            self.status[0]['ChargeRate'] = value
            self.assertEqual(battery_power_label(self.read()), 'Charging — rate unavailable')
        self.status[0]['ChargeRate'] = 18400
        for capabilities in (0x40000000, None):
            self.static[0]['Capabilities'] = capabilities
            self.assertIsNone(self.read()['rate_watts'])
        self.assertEqual(battery_power_label({'power_state': 'AC power (charging unconfirmed)'}),
                         'AC power — rate unavailable')

    def test_reversed_packs_match_their_own_capacity_and_rate(self):
        static = self.static + [dict(InstanceName='B', Capabilities=0)]
        full = [dict(InstanceName='B', FullChargedCapacity=40000)] + self.full
        status = [dict(InstanceName='b', Charging=False, Discharging=True,
                       PowerOnline=False, RemainingCapacity=8000,
                       ChargeRate=0, DischargeRate=7600)] + self.status
        for index, percent, watts in ((0, 90, 18.4), (1, 20, 7.6)):
            state = native_battery_live_state(static, full, status, index, 2)
            self.assertEqual(state['percent'], percent)
            self.assertEqual(state['rate_watts'], watts)
        self.assertIsNone(native_battery_live_state(static, full, status, 0, 3))
        self.assertIsNone(native_battery_live_state(static, full, status + status[:1], 0, 2))
        self.status[0]['Discharging'] = True
        self.assertIsNone(self.read())

    def test_missing_native_provider_keeps_standard_charge_reading(self):
        client = Mock()
        client.Win32_Battery.return_value = [SimpleNamespace(
            EstimatedChargeRemaining=90, BatteryStatus=2)]
        with patch.object(helpers, '_ensure_wmi_instance', return_value=client), \
                patch.object(helpers.wmi, 'WMI', side_effect=RuntimeError('unsupported')):
            state = helpers.get_live_battery_state()
        self.assertEqual(state['percent'], 90)
        self.assertIsNone(state['charging'])
        self.assertEqual(battery_power_label(state), 'AC power — rate unavailable')

    def test_native_capture_joins_before_merging_with_inventory(self):
        client = Mock()
        client.Win32_Battery.return_value = [SimpleNamespace(
            EstimatedChargeRemaining=90, BatteryStatus=2)]
        provider = Mock()
        for name, rows in (('BatteryStaticData', self.static),
                           ('BatteryFullChargedCapacity', self.full),
                           ('BatteryStatus', self.status)):
            getattr(provider, name).return_value = [SimpleNamespace(**row) for row in rows]
        with patch.object(helpers, '_ensure_wmi_instance', return_value=client), \
                patch.object(helpers.wmi, 'WMI', return_value=provider):
            state = helpers.get_live_battery_state()
        self.assertEqual(state['rate_watts'], 18.4)

        self.assertTrue(state['charging'])
        self.assertEqual(state['percent'], 90)
        client.Win32_Battery.return_value[0].EstimatedChargeRemaining = None
        client.Win32_Battery.return_value[0].BatteryStatus = None
        with patch.object(helpers, '_ensure_wmi_instance', return_value=client), \
                patch.object(helpers.wmi, 'WMI', return_value=provider):
            state = helpers.get_live_battery_state()
        self.assertEqual(state['percent'], 90)
        self.assertEqual(state['rate_watts'], 18.4)

    def test_battery_bar_keeps_valid_pack_reading_without_aggregate_fallback(self):
        live = dict(percent=73, state='measured', charging=True,
                    rate_watts=12.5, rate_state='measured')
        with patch.object(helpers, 'get_live_battery_state', return_value=live), \
                patch.object(psutil, 'sensors_battery') as fallback:
            self.assertEqual(helpers.get_battery_bar_state(), live)
        fallback.assert_not_called()

    def test_battery_bar_uses_fresh_windows_charge_when_wmi_is_unreadable(self):
        for plugged, power, charging in (
                (True, 'AC power (charging unconfirmed)', None),
                (False, 'Discharging', False),
                (None, 'Unknown', None)):
            with self.subTest(plugged=plugged), \
                    patch.object(helpers, 'get_live_battery_state', return_value={
                        'percent': None, 'state': 'unreadable'}), \
                    patch.object(psutil, 'sensors_battery', return_value=SimpleNamespace(
                        percent=73, power_plugged=plugged)):
                live = helpers.get_battery_bar_state()
            self.assertEqual(live['percent'], 73)
            self.assertEqual(live['power_state'], power)
            self.assertIs(live['charging'], charging)
            self.assertTrue(live['aggregate'])
            self.assertIsNone(live['rate_watts'])
            self.assertEqual(live['source'], 'Windows power status')

    def test_battery_bar_fallback_accepts_zero_and_full_charge(self):
        for percent, plugged, power in ((0, False, 'Discharging'),
                                        (100, True, 'Fully charged')):
            with patch.object(helpers, 'get_live_battery_state', return_value={
                    'percent': None, 'state': 'absent'}), \
                    patch.object(psutil, 'sensors_battery', return_value=SimpleNamespace(
                        percent=percent, power_plugged=plugged)):
                live = helpers.get_battery_bar_state()
            self.assertEqual(live['percent'], percent)
            self.assertEqual(live['power_state'], power)
            self.assertIs(live['charging'], False)

    def test_battery_bar_does_not_invent_charge_when_all_providers_fail(self):
        original = dict(percent=None, state='unreadable')
        for percent in (None, True, '73', -1, 101, float('nan'), float('inf')):
            with self.subTest(percent=percent), \
                    patch.object(helpers, 'get_live_battery_state', return_value=original), \
                    patch.object(psutil, 'sensors_battery', return_value=SimpleNamespace(
                        percent=percent, power_plugged=True)):
                self.assertEqual(helpers.get_battery_bar_state(), original)
        with patch.object(helpers, 'get_live_battery_state', return_value=original), \
                patch.object(psutil, 'sensors_battery', return_value=None):
            self.assertEqual(helpers.get_battery_bar_state(), original)
        with patch.object(helpers, 'get_live_battery_state', return_value=original), \
                patch.object(psutil, 'sensors_battery', side_effect=OSError('provider failed')), \
                patch('services.runtime.log_diagnostic') as diagnostic:
            self.assertEqual(helpers.get_battery_bar_state(), original)
        self.assertEqual(diagnostic.call_args.kwargs['stage'], 'power_status')

    def test_battery_worker_publishes_fallback_reading(self):
        from services.hardware_job import run_worker
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'request.json').write_text(json.dumps(
                {'kind': 'battery-live', 'arguments': {}}), encoding='utf-8')
            with patch.object(helpers, 'get_live_battery_state', return_value={
                    'state': 'unreadable', 'percent': None}), \
                    patch.object(psutil, 'sensors_battery', return_value=SimpleNamespace(
                        percent=73, power_plugged=True)):
                run_worker(folder)
            reply = json.loads((folder / 'result.json').read_text(encoding='utf-8'))
        self.assertEqual(reply['state'], 'complete')
        self.assertEqual(reply['battery']['percent'], 73)
        self.assertTrue(reply['battery']['aggregate'])


if __name__ == '__main__':
    unittest.main()
