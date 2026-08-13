"""Protocol helpers ported from the Node-RED flow."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import time
from typing import Any

from .const import (
    BATHROOM_MODE_BY_NAME,
    BATHROOM_MODE_MAP,
    COMMAND_UPDATE_STATUS,
    ELECTRIC_MODE_BY_NAME,
    ELECTRIC_MODE_MAP,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class VanwardDeviceInfo:
    """Static data required when sending status updates."""

    device_id: str
    model: str | None = None
    series: str | None = None
    name: str | None = None
    device_type: str | None = None  # e.g. 电热水器 / 燃气热水器（登录 payload Product.Type）


@dataclass(slots=True)
class VanwardDeviceState:
    """Parsed water heater state."""

    raw_status: list[int]
    operational_status: list[int]
    device_info: VanwardDeviceInfo
    electric: bool = False
    # v3.2: 设备在线状态（来自登录 payload isOnline 字段，万和 App 的"设备离线"同源）
    online: bool = True

    @property
    def power(self) -> bool:
        # 电热水器: [1]=电源; 燃气: operational[0] (即原始 status[1])
        if self.electric:
            return bool(self.operational_status[1])
        return bool(self.operational_status[0])

    @property
    def bathroom_mode(self) -> str | None:
        # 双轨：燃气布局模式在重排后 operational[1]（原 status[2]）；电热在 [4]（C1 修正）
        idx = 4 if self.electric else 1
        mode = self.operational_status[idx]
        table = ELECTRIC_MODE_MAP if self.electric else BATHROOM_MODE_MAP
        value = table.get(mode)
        return value[0] if value else None

    @property
    def target_temperature(self) -> int:
        if self.electric:
            return self.operational_status[6]
        return self.operational_status[2]

    @property
    def current_temperature(self) -> int | None:
        """Current water temperature (electric heaters only)."""
        if self.electric and len(self.operational_status) > 7:
            return self.operational_status[7]
        return None

    @property
    def heating(self) -> bool:
        """Heating state.

        Electric heaters (E-series, 27-field layout): [2] is the heating flag
        (3 = heating, 16 = idle) — confirmed by 3-point capture on 2026-08-11.
        Gas heaters: bit 0 of raw_status[8].
        """
        if self.electric:
            return self.operational_status[2] == 3
        return _raw_bit_enabled(self.raw_status, 8, 0x01)

    @property
    def boost(self) -> bool:
        return _bit_enabled(self.operational_status[5], 2)

    @property
    def cruise_mode(self) -> str:
        cruise_flags = self.operational_status[5]
        booking_mode = self.operational_status[11]
        if booking_mode == 1:
            return "预约"
        if booking_mode == 2:
            return "自学习"
        if _bit_enabled(cruise_flags, 1):
            return "点动"
        if _bit_enabled(cruise_flags, 7):
            return "全天候"
        return "关闭"

    @property
    def cruise_temperature(self) -> int:
        return self.operational_status[6]

    @property
    def single_cruise(self) -> bool:
        return _bit_enabled(self.operational_status[5], 0)

    @property
    def enjoy_cruise(self) -> bool:
        return _bit_enabled(self.operational_status[5], 3)

    @property
    def current_water_usage(self) -> float | None:
        return _scale_status(self.raw_status, 11)

    @property
    def current_gas_usage(self) -> float | None:
        return _scale_status(self.raw_status, 17)

    @property
    def total_water_usage(self) -> float | None:
        return _scale_status(self.raw_status, 14)

    @property
    def total_gas_usage(self) -> float | None:
        return _scale_status(self.raw_status, 15)

    @property
    def water_flowing(self) -> bool:
        return _raw_bit_enabled(self.raw_status, 8, 0x02)

    @property
    def antifreeze(self) -> bool:
        return _raw_bit_enabled(self.raw_status, 8, 0x04)

    @property
    def fan(self) -> bool:
        return _raw_bit_enabled(self.raw_status, 8, 0x08)


def encode_message(command: int, payload: dict[str, Any] | None = None) -> bytes:
    """Encode a WebSocket frame using the flow's binary format."""

    body = b""
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    frame = bytes([command]) + len(body).to_bytes(4, "big") + body
    if not body:
        frame += b"\x00"
    return frame


def decode_message(message: bytes | bytearray) -> tuple[int, dict[str, Any]]:
    """Decode a WebSocket frame into command and JSON payload."""

    if len(message) < 5:
        raise ValueError("Message is shorter than the 5 byte header")
    command = message[0]
    length = int.from_bytes(message[1:5], "big")
    payload_bytes = bytes(message[5 : 5 + length])
    if not payload_bytes:
        return command, {}
    try:
        return command, json.loads(payload_bytes.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        _LOGGER.debug(
            "Ignoring non-JSON Vanward frame for command 0x%02x: %r",
            command,
            payload_bytes,
        )
        return command, {}


def states_from_login_payload(payload: dict[str, Any]) -> dict[str, VanwardDeviceState]:
    """Build all device states returned by login."""

    devices = payload.get("data", {}).get("Devices") or payload.get("Devices") or []
    _LOGGER.debug(
        "[vanward] login payload keys: %s; devices count: %d",
        list(payload.keys()),
        len(devices),
    )
    for i, device in enumerate(devices):
        status = device.get("Status")
        _LOGGER.debug(
            "[vanward] device[%d] keys=%s status_len=%s status=%s",
            i,
            list(device.keys()),
            len(status) if status is not None else None,
            status,
        )
    states: dict[str, VanwardDeviceState] = {}
    for device in devices:
        raw_device_id = device.get("DeviceId")
        status = device.get("Status")
        if raw_device_id is None or not status:
            continue
        device_id = str(raw_device_id)
        product = device.get("Product") or {}
        info = VanwardDeviceInfo(
            device_id=device_id,
            model=product.get("Model"),
            series=product.get("Series"),
            name=device.get("Name") or product.get("Name"),
            device_type=product.get("Type") or device.get("catagoryName"),
        )
        try:
            state = state_from_status(status, info)
            # v3.2: 设备在线状态（isOnline，万和 App 离线显示同源）
            # 老版本 payload 无此字段时保持默认 True（不误判离线）
            if "isOnline" in device:
                state.online = bool(device["isOnline"])
            states[device_id] = state
        except ValueError as err:
            # 容错：字段数不够时不崩，打日志继续
            _LOGGER.error(
                "[vanward] device %s state parse failed: %s; raw_status=%s",
                device_id,
                err,
                status,
            )
    return states


def state_from_status(
    status: list[int], device_info: VanwardDeviceState
) -> VanwardDeviceState:
    """Convert the raw status list into the writable operational status list.

    Supports two layouts:
      - gas heater:  >= 34 fields (author's original layout)
      - electric heater: 27 fields (e.g. E60-Q2WY10-20)
          [1] power, [6] target temperature, [7] current temperature
    """

    if len(status) >= 34:
        # 燃气布局（原逻辑）
        operational_status = [
            status[1],
            status[2],
            status[6],
            status[25],
            status[4],
            status[18],
            status[19],
            status[20],
            status[21],
            0,
            0,
            status[33],
        ]
    elif len(status) >= 27:
        # 电热水器布局（27 字段，读写同布局）
        _LOGGER.info(
            "[vanward] electric heater layout detected (len=%d) for %s",
            len(status),
            device_info.device_id,
        )
        operational_status = list(status)
    else:
        _LOGGER.error(
            "[vanward] unsupported status length %d: %s",
            len(status),
            status,
        )
        raise ValueError("Status payload does not contain the expected fields")

    return VanwardDeviceState(
        raw_status=list(status),
        operational_status=operational_status,
        device_info=device_info,
        electric=(
            "电" in (device_info.device_type or "")
            or len(status) < 34
        ),
    )


def clone_state(state: VanwardDeviceState) -> VanwardDeviceState:
    """Copy a device state before preparing a writable status update."""

    return VanwardDeviceState(
        raw_status=list(state.raw_status),
        operational_status=list(state.operational_status),
        device_info=state.device_info,
    )


def update_status_payload(state: VanwardDeviceState) -> tuple[int, dict[str, Any]]:
    """Create the update-status command payload."""

    info = state.device_info
    return (
        COMMAND_UPDATE_STATUS,
        {
            "Id": info.device_id,
            "MsgId": 1,
            "Model": info.model,
            "Series": info.series,
            "Status": state.operational_status,
            "Timestamp": int(time.time()),
        },
    )


def set_power(state: VanwardDeviceState, enabled: bool) -> bool:
    value = int(enabled)
    idx = 1 if state.electric else 0
    if state.operational_status[idx] == value:
        return False
    state.operational_status[idx] = value
    return True


def set_boost(state: VanwardDeviceState, enabled: bool) -> bool:
    return _set_status_bit(state, 2, enabled)


def set_target_temperature(state: VanwardDeviceState, temperature: int) -> bool:
    idx = 6 if state.electric else 2
    if state.operational_status[idx] == temperature:
        return False
    state.operational_status[idx] = temperature
    return True


def set_cruise_temperature(state: VanwardDeviceState, temperature: int) -> bool:
    if state.operational_status[6] == temperature:
        return False
    state.operational_status[6] = temperature
    return True


def set_single_cruise(state: VanwardDeviceState, enabled: bool) -> bool:
    changed = _set_status_bit(state, 0, enabled)
    if changed and enabled:
        state.operational_status[0] = 1
    return changed


def set_enjoy_cruise(state: VanwardDeviceState, enabled: bool) -> bool:
    return _set_status_bit(state, 3, enabled)


def set_cruise_mode(state: VanwardDeviceState, option: str) -> bool:
    if state.single_cruise:
        raise ValueError("Cruise mode cannot be changed while single cruise is enabled")

    before = list(state.operational_status)
    status = state.operational_status[5]
    if option == "预约":
        status = _replace_bit(status, 1, False)
        status = _replace_bit(status, 7, False)
        state.operational_status[5] = status
        state.operational_status[9] = 0
        state.operational_status[11] = 1
    elif option == "自学习":
        status = _replace_bit(status, 1, False)
        status = _replace_bit(status, 7, False)
        state.operational_status[5] = status
        state.operational_status[9] = 0
        state.operational_status[11] = 2
    elif option == "点动":
        status = _replace_bit(status, 1, True)
        status = _replace_bit(status, 7, False)
        state.operational_status[5] = status
        state.operational_status[9] = 0
        state.operational_status[11] = 0
    elif option == "全天候":
        status = _replace_bit(status, 1, False)
        status = _replace_bit(status, 7, True)
        state.operational_status[5] = status
        state.operational_status[9] = 0
        state.operational_status[11] = 0
    elif option == "关闭":
        status = _replace_bit(status, 1, False)
        status = _replace_bit(status, 7, False)
        state.operational_status[5] = status
        state.operational_status[9] = 0
        state.operational_status[11] = 0
    else:
        raise ValueError(f"Unsupported cruise mode: {option}")
    return before != state.operational_status


def set_bathroom_mode(state: VanwardDeviceState, option: str) -> bool:
    # 双轨：燃气模式写重排后 operational[1]，电热写 [4]（C1 修正）
    table = ELECTRIC_MODE_BY_NAME if state.electric else BATHROOM_MODE_BY_NAME
    mode_data = table.get(option)
    if mode_data is None:
        raise ValueError(f"Unsupported bathroom mode: {option}")

    mode, _temperature, _cruise_temperature = mode_data
    idx = 4 if state.electric else 1
    if state.operational_status[idx] == mode:
        return False
    state.operational_status[idx] = mode
    return True


def press_call(state: VanwardDeviceState) -> bool:
    state.operational_status[10] = 8
    return True


def _scale_status(status: list[int], index: int) -> float | None:
    if len(status) <= index:
        return None
    return round(status[index] * 0.1, 1)


def _raw_bit_enabled(status: list[int], index: int, mask: int) -> bool:
    if len(status) <= index:
        return False
    return bool(status[index] & mask)


def _bit_enabled(value: int, index: int) -> bool:
    # 位序约定（N1 注释）：字符串高位索引，index 0 = MSB —— 燃气原逻辑，勿改
    return f"{value:08b}"[index] == "1"


def _mask_enabled(value: int, mask: int) -> bool:
    # 低位掩码风格，bit0 = LSB（电热 Status[24] 功能位用，如 bit1 = 0x02）
    return bool(value & mask)


def _set_mask(value: int, mask: int, enabled: bool) -> int:
    # 低位掩码置位/清位（电热 Status[24] 功能位用）
    return value | mask if enabled else value & ~mask


def _set_status_bit(state: VanwardDeviceState, bit_index: int, enabled: bool) -> bool:
    value = state.operational_status[5]
    updated = _replace_bit(value, bit_index, enabled)
    if value == updated:
        return False
    state.operational_status[5] = updated
    return True


def _replace_bit(value: int, index: int, enabled: bool) -> int:
    # 位序约定（N1 注释）：字符串高位索引，index 0 = MSB —— 燃气原逻辑，勿改
    bits = list(f"{value:08b}")
    bits[index] = "1" if enabled else "0"
    return int("".join(bits), 2)
