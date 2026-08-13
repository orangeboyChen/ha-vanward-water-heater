"""Number entities for Vanward water heaters."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import VanwardCoordinator
from .entity import VanwardEntity
from .protocol import VanwardDeviceState

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class VanwardNumberDescription(NumberEntityDescription):
    """Description for Vanward number entities."""

    value_fn: Callable[[VanwardDeviceState], int]
    set_fn: Callable[[VanwardCoordinator, int], Awaitable[None]]


NUMBERS = [
    VanwardNumberDescription(
        key="cruise_temperature",
        translation_key="cruise_temperature",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=34,
        native_max_value=43,
        native_step=1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda state: state.cruise_temperature,
        set_fn=lambda coordinator, value: coordinator.client.async_set_cruise_temperature(
            coordinator.device_id, value
        ),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    # C3：巡航温度是燃气功能，电热机型不注册
    coordinators = [
        c for c in entry.runtime_data.coordinators.values() if not c.data.electric
    ]
    entities = [
        VanwardNumber(coordinator, description)
        for coordinator in coordinators
        for description in NUMBERS
    ]
    _LOGGER.debug("Adding %s Vanward number entities", len(entities))
    async_add_entities(entities)


class VanwardNumber(VanwardEntity, NumberEntity):
    """Number entity."""

    def __init__(
        self,
        coordinator: VanwardCoordinator,
        description: VanwardNumberDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.translation_key)
        self.entity_description = description

    @property
    def native_value(self) -> int:
        return self.entity_description.value_fn(self.coordinator.data)

    async def async_set_native_value(self, value: float) -> None:
        await self.entity_description.set_fn(self.coordinator, int(value))
