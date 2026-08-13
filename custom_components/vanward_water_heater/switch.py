"""Switch entities for Vanward water heaters."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import VanwardCoordinator
from .entity import VanwardEntity
from .protocol import VanwardDeviceState

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class VanwardSwitchDescription(SwitchEntityDescription):
    """Description for Vanward switch entities."""

    value_fn: Callable[[VanwardDeviceState], bool]
    set_fn: Callable[[VanwardCoordinator, bool], Awaitable[None]]


SWITCHES = [
    VanwardSwitchDescription(
        key="boost",
        translation_key="boost",
        value_fn=lambda state: state.boost,
        set_fn=lambda coordinator, enabled: coordinator.client.async_set_boost(
            coordinator.device_id, enabled
        ),
    ),
    VanwardSwitchDescription(
        key="single_cruise",
        translation_key="single_cruise",
        value_fn=lambda state: state.single_cruise,
        set_fn=lambda coordinator, enabled: coordinator.client.async_set_single_cruise(
            coordinator.device_id, enabled
        ),
    ),
    VanwardSwitchDescription(
        key="enjoy_cruise",
        translation_key="enjoy_cruise",
        value_fn=lambda state: state.enjoy_cruise,
        set_fn=lambda coordinator, enabled: coordinator.client.async_set_enjoy_cruise(
            coordinator.device_id, enabled
        ),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    # C3：单次/E享/水增压是燃气功能，电热机型不注册
    coordinators = [
        c for c in entry.runtime_data.coordinators.values() if not c.data.electric
    ]
    entities = [
        VanwardSwitch(coordinator, description)
        for coordinator in coordinators
        for description in SWITCHES
    ]
    _LOGGER.debug("Adding %s Vanward switch entities", len(entities))
    async_add_entities(entities)


class VanwardSwitch(VanwardEntity, SwitchEntity):
    """Switch entity."""

    def __init__(
        self,
        coordinator: VanwardCoordinator,
        description: VanwardSwitchDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.translation_key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return self.entity_description.value_fn(self.coordinator.data)

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.entity_description.set_fn(self.coordinator, True)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.entity_description.set_fn(self.coordinator, False)
