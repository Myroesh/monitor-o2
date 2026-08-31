"""Unit tests for SimulatedEsp32Client device info & configuration validation."""
import pytest
from app.services.esp32_client import SimulatedEsp32Client


class TestEsp32Client:
    def test_client_instantiates(self):
        client = SimulatedEsp32Client()
        assert client is not None

    def test_read_returns_expected_keys(self):
        sample = SimulatedEsp32Client().read()
        assert "connected" in sample
        assert "o2_pct" in sample
        assert "p_calibrated_kpa" in sample
        assert "p_ema_kpa" in sample
        assert "p_nominal_kpa" in sample
        assert "ain0_mv" in sample
        assert "vs_mpx_mv" in sample

    def test_get_device_info_schema(self):
        client = SimulatedEsp32Client()
        info = client.get_device_info()
        required_keys = {
            "connected", "status", "firmware_version", "uptime_seconds",
            "ads1115_status", "ads1115_i2c_address", "ads1115_data_rate",
            "vs_mpx_mv", "calibration_origin", "gain", "offset",
            "rtop_ain0", "rbottom_ain0", "ratio_ain0",
            "rtop_ain1", "rbottom_ain1", "ratio_ain1",
            "ocs3f_frames_ok", "ocs3f_frames_error", "is_simulated",
        }
        assert required_keys.issubset(info.keys())
        assert info["is_simulated"] is True
        assert info["vs_mpx_mv"] == 5020.0

    def test_vs_mpx_mv_telemetry_near_5020(self):
        client = SimulatedEsp32Client()
        sample = client.read()
        assert 5000.0 < sample["vs_mpx_mv"] < 5050.0

    def test_default_firmware_values_and_calculated_ratios(self):
        client = SimulatedEsp32Client()
        info = client.get_device_info()

        assert info["gain"] == 1.02677
        assert info["offset"] == -3.388341
        assert info["rtop_ain0"] == 32700.0
        assert info["rbottom_ain0"] == 21800.0
        # 21800 / (32700 + 21800) = 0.4000
        assert info["ratio_ain0"] == 0.4

        assert info["rtop_ain1"] == 33300.0
        assert info["rbottom_ain1"] == 21500.0
        # 21500 / (33300 + 21500) ≈ 0.392336
        assert pytest.approx(info["ratio_ain1"], 0.0001) == 0.392336

    def test_update_config_valid(self):
        client = SimulatedEsp32Client()
        updated = client.update_config({
            "gain": 2.5,
            "offset": 5.0,
            "rtop_ain0": 30000.0,
            "rbottom_ain0": 10000.0,
        })
        assert updated["gain"] == 2.5
        assert updated["offset"] == 5.0
        assert updated["rtop_ain0"] == 30000.0
        # 10000 / (30000 + 10000) = 0.25
        assert updated["ratio_ain0"] == 0.25

    def test_update_config_invalid_gain_bounds(self):
        client = SimulatedEsp32Client()
        with pytest.raises(ValueError, match="GAIN"):
            client.update_config({"gain": 0.05})

        with pytest.raises(ValueError, match="GAIN"):
            client.update_config({"gain": 10.5})

    def test_update_config_invalid_offset_bounds(self):
        client = SimulatedEsp32Client()
        with pytest.raises(ValueError, match="OFFSET"):
            client.update_config({"offset": -501.0})

        with pytest.raises(ValueError, match="OFFSET"):
            client.update_config({"offset": 501.0})

    def test_update_config_invalid_resistors(self):
        client = SimulatedEsp32Client()
        with pytest.raises(ValueError, match="Rtop AIN0"):
            client.update_config({"rtop_ain0": 50.0})

    def test_update_config_invalid_ratio_bounds(self):
        client = SimulatedEsp32Client()
        with pytest.raises(ValueError, match="Ratio"):
            # 100000 / (1000 + 100000) = 0.99 > 0.95
            client.update_config({"rtop_ain0": 1000.0, "rbottom_ain0": 100000.0})
