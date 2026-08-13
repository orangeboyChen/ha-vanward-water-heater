"""Binary sensor entities for Vanward water heaters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import VanwardCoordinator
from .entity import VanwardEntity
from .protocol import VanwardDeviceState

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class VanwardBinarySensorDescription(BinarySensorEntityDescription):
    """Description for Vanward binary sensor entities."""

    value_fn: Callable[[VanwardDeviceState], bool]


BINARY_SENSORS = [
    VanwardBinarySensorDescription(
        key="heating",
        translation_key="heating",
        icon="mdi:fire",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda state: state.heating,
    ),
    VanwardBinarySensorDescription(
        key="water_flowing",
        translation_key="water_flowing",
        icon="mdi:water-pump",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda state: state.water_flowing,
    ),
    VanwardBinarySensorDescription(
        key="fan",
        translation_key="fan",
        icon="mdi:fan",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda state: state.fan,
    ),
    VanwardBinarySensorDescription(
        key="antifreeze",
        translation_key="antifreeze",
        icon="mdi:snowflake",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda state: state.antifreeze,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    # C3：heating 对电热有效（[2]==3 实测锚定）；水流量/风扇/防冻是燃气专属，电热跳过
    coordinators = entry.runtime_data.coordinators.values()
    entities = [
        VanwardBinarySensor(coordinator, description)
        for coordinator in coordinators
        for description in BINARY_SENSORS
        if not coordinator.data.electric or description.key == "heating"
    ]
    _LOGGER.debug("Adding %s Vanward binary sensor entities", len(entities))
    async_add_entities(entities)


class VanwardBinarySensor(VanwardEntity, BinarySensorEntity):
    """Binary sensor entity."""

    def __init__(
        self,
        coordinator: VanwardCoordinator,
        description: VanwardBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.translation_key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return self.entity_description.value_fn(self.coordinator.data)
