"""Live rates use matched battery identities and documented milliwatt units."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from services.measurements import native_battery_live_state, battery_power_label
from utils import helpers


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


if __name__ == '__main__':
    unittest.main()
