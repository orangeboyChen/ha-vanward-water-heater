"""Water heater entity for Vanward water heaters."""

from __future__ import annotations

import logging

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, STATE_OFF, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    BATHROOM_MODE_OPTIONS,
    ELECTRIC_MODE_OPTIONS,
    ELECTRIC_MAX_TEMP,
    ELECTRIC_MIN_TEMP,
)
from .coordinator import VanwardCoordinator
from .entity import VanwardEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinators = entry.runtime_data.coordinators.values()
    entities = [VanwardWaterHeater(coordinator) for coordinator in coordinators]
    _LOGGER.debug("Adding %s Vanward water heater entities", len(entities))
    async_add_entities(entities)


class VanwardWaterHeater(VanwardEntity, WaterHeaterEntity):
    """Water heater entity."""

    _attr_target_temperature_step = 1
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
        | WaterHeaterEntityFeature.ON_OFF
    )

    def __init__(self, coordinator: VanwardCoordinator) -> None:
        # v3.3.1: translation_key 置 None——主实体名直接继承设备名"热水器"，
        # 避免 device_info.name + 实体翻译名拼接成"热水器 热水器"
        super().__init__(coordinator, "water_heater", None)

    @property
    def min_temp(self) -> int:
        # M1：双轨温度范围——电热 35-75（产品资料），燃气 30-65（作者原值）
        return ELECTRIC_MIN_TEMP if self.coordinator.data.electric else 30

    @property
    def max_temp(self) -> int:
        return ELECTRIC_MAX_TEMP if self.coordinator.data.electric else 65

    @property
    def operation_list(self) -> list[str]:
        # N5：operation_list 双轨——电热 Q2 模式（1/2/10/12/32/35/43），燃气原样
        if self.coordinator.data.electric:
            return [STATE_OFF, *ELECTRIC_MODE_OPTIONS]
        return [STATE_OFF, *BATHROOM_MODE_OPTIONS]

    @property
    def current_operation(self) -> str | None:
        state = self.coordinator.data
        if not state.power:
            return STATE_OFF
        return state.bathroom_mode

    @property
    def target_temperature(self) -> int:
        return self.coordinator.data.target_temperature

    @property
    def current_temperature(self) -> float | None:
        """Current water temperature (electric heaters)."""
        return self.coordinator.data.current_temperature

    @property
    def target_temperature_high(self) -> int | None:
        # N4：自适温仅燃气模式有；电热无此模式，返回 None
        if (
            not self.coordinator.data.electric
            and self.coordinator.data.bathroom_mode == "自适温"
        ):
            return self.coordinator.data.target_temperature
        return None

    @property
    def target_temperature_low(self) -> int | None:
        if (
            not self.coordinator.data.electric
            and self.coordinator.data.bathroom_mode == "自适温"
        ):
            return self.coordinator.data.target_temperature
        return None

    async def async_set_temperature(self, **kwargs: object) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        # N4：自适温忽略逻辑仅燃气有效（电热无此模式，正常设温）
        if (
            not self.coordinator.data.electric
            and self.coordinator.data.bathroom_mode == "自适温"
        ):
            _LOGGER.debug("Ignoring target temperature change in adaptive mode")
            return
        await self.coordinator.client.async_set_target_temperature(
            self.coordinator.device_id, int(float(temperature))
        )

    async def async_turn_on(self) -> None:
        await self.coordinator.client.async_set_power(self.coordinator.device_id, True)

    async def async_turn_off(self) -> None:
        await self.coordinator.client.async_set_power(
            self.coordinator.device_id, False
        )

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        if operation_mode == STATE_OFF:
            await self.async_turn_off()
            return
        await self.async_turn_on()
        await self.coordinator.client.async_set_bathroom_mode(
            self.coordinator.device_id, operation_mode
        )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """暴露原始 27 字段状态数组（字段反推用）。

        N3 注：raw_status 全量数组会被 HA recorder 记录，长期运行有数据噪音；
        字段锁定后可考虑仅调试期暴露或 recorder exclude。
        """
        attrs = dict(super().extra_state_attributes or {})
        attrs["raw_status"] = self.coordinator.data.raw_status
        return attrs
