"""Tests for the Vanward electric water heater protocol logic (v3.1).

Covers: electric mode code table, dual-track read/write (Status[4]/Status[6]),
state layout detection (27-field electric vs 34-field gas), bitmask helpers,
frame encode/decode. Pure logic — no Home Assistant runtime needed.
"""

import pytest

from custom_components.vanward_water_heater import protocol
from custom_components.vanward_water_heater.const import (
    BATHROOM_MODE_BY_NAME,
    BATHROOM_MODE_MAP,
    ELECTRIC_MAX_TEMP,
    ELECTRIC_MODE_BY_NAME,
    ELECTRIC_MODE_MAP,
    ELECTRIC_MIN_TEMP,
)

# ── 真实捕获的 E60-Q2WY10-20 电热 27 字段状态（2026-08-13 装机验证）──
# [1]=电源(1开) [2]=加热标志(16空闲) [4]=模式(1普通) [6]=目标42 [7]=当前42
ELECTRIC_STATUS_27 = [
    0, 1, 16, 0, 1, 17, 42, 42, 0, 0, 0, 0, 1, 51, 0, 0, 0, 0, 5, 0, 0, 4, 4, 5, 0, 0, 0,
]


def _electric_state(status: list[int] | None = None) -> protocol.VanwardDeviceState:
    status = status if status is not None else list(ELECTRIC_STATUS_27)
    info = protocol.VanwardDeviceInfo(device_id="test", device_type="电热水器")
    return protocol.state_from_status(status, info)


def _gas_state() -> protocol.VanwardDeviceState:
    # 34+ 字段燃气布局（原版作者逻辑，重排后）：
    #   operational[0] = status[1] 电源
    #   operational[1] = status[2] 模式
    #   operational[2] = status[6] 目标温度
    status = [0] * 34
    status[1] = 1   # 电源开
    status[2] = 1   # 模式：普通
    status[6] = 42  # 目标温度
    info = protocol.VanwardDeviceInfo(device_id="test-gas", device_type="燃气热水器")
    return protocol.state_from_status(status, info)


# ───────────────────────── 模式码表（C2） ─────────────────────────

class TestElectricModeCodeTable:
    def test_mode_map_keys(self):
        assert set(ELECTRIC_MODE_MAP.keys()) == {1, 2, 10, 12, 32, 35, 43}

    def test_mode_names(self):
        names = [v[0] for v in ELECTRIC_MODE_MAP.values()]
        assert names == ["普通", "中温", "抑菌", "增容", "ECO峰谷", "e-push", "e-push"]

    def test_mode_by_name_roundtrip(self):
        for name, code in [
            ("普通", 1), ("中温", 2), ("抑菌", 10),
            ("增容", 12), ("ECO峰谷", 32), ("e-push", 35),
        ]:
            assert ELECTRIC_MODE_BY_NAME[name][0] == code

    def test_mode_43_normalizes_to_epush(self):
        # e-push 带自动断电标志时读值 43 → 显示归一到 e-push
        assert ELECTRIC_MODE_MAP[43][0] == "e-push"

    def test_electric_vs_gas_tables_distinct(self):
        # 电热码表与燃气码表必须不同（C2 修复点：此前误用燃气表）
        assert set(ELECTRIC_MODE_MAP.keys()) != set(BATHROOM_MODE_MAP.keys())

    def test_temp_range(self):
        assert ELECTRIC_MIN_TEMP == 35
        assert ELECTRIC_MAX_TEMP == 75


# ───────────────────────── 状态布局识别 ─────────────────────────

class TestStateLayoutDetection:
    def test_electric_27_field_detected(self):
        state = _electric_state()
        assert state.electric is True
        assert state.operational_status == ELECTRIC_STATUS_27

    def test_gas_34_field_detected(self):
        state = _gas_state()
        assert state.electric is False

    def test_unsupported_short_status_raises(self):
        info = protocol.VanwardDeviceInfo(device_id="x")
        with pytest.raises(ValueError, match="expected fields"):
            protocol.state_from_status([0, 1, 2], info)


# ───────────────────────── 双轨读取（C1） ─────────────────────────

class TestDualTrackRead:
    def test_electric_power_at_idx1(self):
        state = _electric_state()
        assert state.power is True
        state.operational_status[1] = 0
        assert state.power is False

    def test_electric_mode_at_idx4(self):
        # C1 修复点：电热模式读 operational[4]（不是燃气版 [1]）
        state = _electric_state()
        assert state.bathroom_mode == "普通"
        state.operational_status[4] = 32  # ECO峰谷
        assert state.bathroom_mode == "ECO峰谷"
        state.operational_status[4] = 35  # e-push
        assert state.bathroom_mode == "e-push"
        state.operational_status[4] = 43  # 带标志读值 → 归一
        assert state.bathroom_mode == "e-push"

    def test_electric_target_temp_at_idx6(self):
        state = _electric_state()
        assert state.target_temperature == 42
        state.operational_status[6] = 60
        assert state.target_temperature == 60

    def test_electric_current_temp_at_idx7(self):
        state = _electric_state()
        assert state.current_temperature == 42

    def test_gas_mode_at_reordered_idx1(self):
        state = _gas_state()
        assert state.bathroom_mode == "普通"
        state.operational_status[1] = 24  # 儿童浴
        assert state.bathroom_mode == "儿童浴"

    def test_gas_target_temp_at_idx2(self):
        state = _gas_state()
        assert state.target_temperature == 42

    def test_gas_has_no_current_temp(self):
        state = _gas_state()
        assert state.current_temperature is None

    def test_electric_heating_flag(self):
        state = _electric_state()
        assert state.heating is False  # [2]=16 空闲
        state.operational_status[2] = 3  # 加热
        assert state.heating is True


# ───────────────────────── 双轨写入 ─────────────────────────

class TestDualTrackWrite:
    def test_set_power_electric_idx1(self):
        state = _electric_state()
        assert protocol.set_power(state, False) is True
        assert state.operational_status[1] == 0
        assert protocol.set_power(state, False) is False  # 无变化

    def test_set_power_gas_idx0(self):
        state = _gas_state()
        assert protocol.set_power(state, False) is True
        assert state.operational_status[0] == 0

    def test_set_target_temperature_electric_idx6(self):
        state = _electric_state()
        assert protocol.set_target_temperature(state, 60) is True
        assert state.operational_status[6] == 60

    def test_set_target_temperature_gas_idx2(self):
        state = _gas_state()
        assert protocol.set_target_temperature(state, 50) is True
        assert state.operational_status[2] == 50

    def test_set_bathroom_mode_electric_idx4(self):
        state = _electric_state()
        assert protocol.set_bathroom_mode(state, "ECO峰谷") is True
        assert state.operational_status[4] == 32
        assert protocol.set_bathroom_mode(state, "e-push") is True
        assert state.operational_status[4] == 35
        assert protocol.set_bathroom_mode(state, "普通") is True
        assert state.operational_status[4] == 1

    def test_set_bathroom_mode_gas_idx1(self):
        state = _gas_state()
        assert protocol.set_bathroom_mode(state, "儿童浴") is True
        assert state.operational_status[1] == 24

    def test_set_bathroom_mode_invalid_raises(self):
        state = _electric_state()
        with pytest.raises(ValueError, match="Unsupported bathroom mode"):
            protocol.set_bathroom_mode(state, "自适温")  # 电热无此模式

    def test_update_status_payload_uses_operational_status(self):
        state = _electric_state()
        cmd, payload = protocol.update_status_payload(state)
        assert cmd == 0x04
        assert payload["Status"] == ELECTRIC_STATUS_27
        assert payload["Id"] == "test"


# ───────────────────────── 功能位掩码（N1） ─────────────────────────

class TestBitmaskHelpers:
    def test_mask_enabled_lsb_style(self):
        # 低位掩码风格：bit0=0x01, bit1=0x02（电热 Status[24] 功能位）
        assert protocol._mask_enabled(0b00000010, 0x02) is True
        assert protocol._mask_enabled(0b00000001, 0x02) is False

    def test_set_mask_clear(self):
        assert protocol._set_mask(0b00000010, 0x02, False) == 0
        assert protocol._set_mask(0, 0x02, True) == 0x02

    def test_legacy_bit_index_msb_style_preserved(self):
        # 燃气原逻辑位序（字符串高位索引）不能动（N1 注释）
        assert protocol._bit_enabled(0b10000000, 0) is True  # MSB
        assert protocol._replace_bit(0b00000000, 0, True) == 0b10000000


# ───────────────────────── 帧编解码 ─────────────────────────

class TestFrameEncodeDecode:
    def test_encode_with_payload_roundtrip(self):
        payload = {"Id": "abc", "Status": [0, 1, 2]}
        frame = protocol.encode_message(0x04, payload)
        cmd, decoded = protocol.decode_message(frame)
        assert cmd == 0x04
        assert decoded == payload

    def test_encode_empty_payload(self):
        frame = protocol.encode_message(0x0A)
        assert frame[0] == 0x0A
        assert frame[-1] == 0x00  # 空 payload 补零

    def test_decode_short_message_raises(self):
        with pytest.raises(ValueError, match="shorter than"):
            protocol.decode_message(b"\x00\x01")

    def test_decode_non_json_payload_returns_empty(self):
        frame = bytes([0x22]) + (2).to_bytes(4, "big") + b"ab"
        cmd, payload = protocol.decode_message(frame)
        assert cmd == 0x22
        assert payload == {}


# ───────────────────────── 克隆与状态更新 ─────────────────────────

class TestCloneAndUpdate:
    def test_clone_is_independent(self):
        state = _electric_state()
        clone = protocol.clone_state(state)
        clone.operational_status[4] = 32
        assert state.operational_status[4] == 1  # 原对象不受影响
        assert clone.raw_status == state.raw_status


# ───────────────────────── 设备在线状态（v3.2） ─────────────────────────

class TestDeviceOnline:
    def test_login_payload_online_flag(self):
        # 登录 payload 带 isOnline=true
        payload = {
            "data": {"Devices": [
                {"DeviceId": "dev1", "Status": ELECTRIC_STATUS_27,
                 "isOnline": True, "Product": {}},
            ]}
        }
        states = protocol.states_from_login_payload(payload)
        assert states["dev1"].online is True

    def test_login_payload_offline_flag(self):
        # 设备离线：isOnline=false（万和 App 的"设备离线"同源）
        payload = {
            "data": {"Devices": [
                {"DeviceId": "dev1", "Status": ELECTRIC_STATUS_27,
                 "isOnline": False, "Product": {}},
            ]}
        }
        states = protocol.states_from_login_payload(payload)
        assert states["dev1"].online is False

    def test_login_payload_missing_flag_defaults_online(self):
        # 老版本 payload 无 isOnline 字段时默认为在线（不误判）
        payload = {
            "data": {"Devices": [
                {"DeviceId": "dev1", "Status": ELECTRIC_STATUS_27, "Product": {}},
            ]}
        }
        states = protocol.states_from_login_payload(payload)
        assert states["dev1"].online is True

    def test_state_from_status_keeps_default_online(self):
        state = _electric_state()
        assert state.online is True
