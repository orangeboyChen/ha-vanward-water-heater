"""Select entities for Vanward water heaters."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CRUISE_OPTIONS
from .coordinator import VanwardCoordinator
from .entity import VanwardEntity
from .protocol import VanwardDeviceState

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class VanwardSelectDescription(SelectEntityDescription):
    """Description for Vanward select entities."""

    options: list[str]
    value_fn: Callable[[VanwardDeviceState], str | None]
    set_fn: Callable[[VanwardCoordinator, str], Awaitable[None]]


SELECTS = [
    VanwardSelectDescription(
        key="cruise_mode",
        translation_key="cruise_mode",
        options=CRUISE_OPTIONS,
        value_fn=lambda state: state.cruise_mode,
        set_fn=lambda coordinator, option: coordinator.client.async_set_cruise_mode(
            coordinator.device_id, option
        ),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    # C3：巡航是燃气功能，电热机型不注册
    coordinators = [
        c for c in entry.runtime_data.coordinators.values() if not c.data.electric
    ]
    entities = [
        VanwardSelect(coordinator, description)
        for coordinator in coordinators
        for description in SELECTS
    ]
    _LOGGER.debug("Adding %s Vanward select entities", len(entities))
    async_add_entities(entities)


class VanwardSelect(VanwardEntity, SelectEntity):
    """Select entity."""

    def __init__(
        self,
        coordinator: VanwardCoordinator,
        description: VanwardSelectDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.translation_key)
        self.entity_description = description
        self._attr_options = description.options

    @property
    def current_option(self) -> str | None:
        return self.entity_description.value_fn(self.coordinator.data)

    async def async_select_option(self, option: str) -> None:
        await self.entity_description.set_fn(self.coordinator, option)
