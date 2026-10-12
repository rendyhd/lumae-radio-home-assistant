"""The radio as a device in Home Assistant."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ORIGIN, DOMAIN
from .coordinator import LumaeRadioCoordinator


class LumaeRadioEntity(CoordinatorEntity[LumaeRadioCoordinator]):
    """An entity of one radio, named after it."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: LumaeRadioCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        assert entry.unique_id is not None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
            name=entry.title,
            manufacturer="Lumae",
            model="Lumae Radio",
            configuration_url=entry.data[CONF_ORIGIN],
        )
