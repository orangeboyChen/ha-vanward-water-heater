"""Button entities for Vanward water heaters."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import VanwardCoordinator
from .entity import VanwardEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    # C3：呼叫按钮是燃气功能，电热机型不注册
    coordinators = [
        c for c in entry.runtime_data.coordinators.values() if not c.data.electric
    ]
    entities = [VanwardCallButton(coordinator) for coordinator in coordinators]
    _LOGGER.debug("Adding %s Vanward button entities", len(entities))
    async_add_entities(entities)


class VanwardCallButton(VanwardEntity, ButtonEntity):
    """Call button entity."""

    def __init__(self, coordinator: VanwardCoordinator) -> None:
        super().__init__(coordinator, "call", "call")

    async def async_press(self) -> None:
        await self.coordinator.client.async_press_call(self.coordinator.device_id)
