"""Light platform for BTAlliance Mesh Lights."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_MESH_NAME, BROADCAST_ADDRESS
from .coordinator import BTAllianceMeshCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BTAlliance lights from a config entry."""
    coordinator: BTAllianceMeshCoordinator = hass.data[DOMAIN][entry.entry_id]
    mesh_name = entry.data.get(CONF_MESH_NAME, "Fulife")
    
    # Track which mesh addresses have entities
    known_addresses: set[int] = set()
    
    # Connect to gateway first
    if not await coordinator.async_connect():
        _LOGGER.error("Failed to connect to gateway")
        return
    
    # Discover mesh devices
    _LOGGER.info("Discovering mesh devices...")
    discovered = await coordinator.async_discover_mesh_devices()
    
    # Also include any devices discovered during connection (from 0xDC notifications)
    all_devices = {**coordinator.discovered_devices, **discovered}
    
    if not all_devices:
        _LOGGER.warning("No mesh devices discovered, adding gateway only")
        all_devices = {1: {'is_on': False, 'luminance': 0}}
    
    # Create light entities for each discovered device
    entities = []
    
    for mesh_addr, state in all_devices.items():
        if mesh_addr not in known_addresses:
            known_addresses.add(mesh_addr)
            entities.append(
                BTAllianceMeshLight(
                    coordinator=coordinator,
                    mesh_addr=mesh_addr,
                    mesh_name=mesh_name,
                    entry_id=entry.entry_id,
                )
            )
    
    _LOGGER.info("Adding %d light entities", len(entities))
    async_add_entities(entities)
    
    # Now register callback for future dynamic device discovery
    def add_new_device(mesh_addr: int) -> None:
        """Add a new light entity for a discovered mesh device."""
        if mesh_addr in known_addresses:
            return
        
        known_addresses.add(mesh_addr)
        _LOGGER.info("Adding new light entity for mesh address %d", mesh_addr)
        
        async_add_entities([
            BTAllianceMeshLight(
                coordinator=coordinator,
                mesh_addr=mesh_addr,
                mesh_name=mesh_name,
                entry_id=entry.entry_id,
            )
        ])
    
    coordinator.set_new_device_callback(add_new_device)


class BTAllianceMeshLight(CoordinatorEntity, LightEntity):
    """Representation of a BTAlliance mesh light."""

    _attr_has_entity_name = True
    _attr_supported_color_modes = {ColorMode.RGB, ColorMode.COLOR_TEMP}
    _attr_color_mode = ColorMode.RGB
    _attr_supported_features = LightEntityFeature(0)
    _attr_min_color_temp_kelvin = 2700  # warm
    _attr_max_color_temp_kelvin = 6500  # cool

    def __init__(
        self,
        coordinator: BTAllianceMeshCoordinator,
        mesh_addr: int,
        mesh_name: str,
        entry_id: str,
    ) -> None:
        """Initialize the light."""
        super().__init__(coordinator)
        
        self._mesh_addr = mesh_addr
        self._mesh_name = mesh_name
        self._entry_id = entry_id
        
        # Entity IDs
        self._attr_unique_id = f"{entry_id}_{mesh_addr}"
        self._attr_name = f"Light {mesh_addr}"
        
        # Device info - group all lights under the mesh network
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{mesh_addr}")},
            name=f"{mesh_name} Light {mesh_addr}",
            manufacturer="BTAlliance/Fulife",
            model="Telink BLE Mesh Light",
            via_device=(DOMAIN, entry_id),
        )
        
        # Register for state updates
        coordinator.register_state_callback(mesh_addr, self._handle_state_update)
    
    async def async_will_remove_from_hass(self) -> None:
        """Handle removal from hass."""
        self.coordinator.unregister_state_callback(self._mesh_addr)
        await super().async_will_remove_from_hass()
    
    @callback
    def _handle_state_update(self) -> None:
        """Handle state update from coordinator."""
        self.async_write_ha_state()
    
    @property
    def is_on(self) -> bool | None:
        """Return true if light is on."""
        state = self.coordinator.get_light_state(self._mesh_addr)
        if state:
            return state.get('is_on', False)
        return None
    
    @property
    def brightness(self) -> int | None:
        """Return the brightness of the light (0-255)."""
        state = self.coordinator.get_light_state(self._mesh_addr)
        if state and state.get('luminance') is not None:
            # Convert 0-100 to 0-255
            return int(state['luminance'] * 255 / 100)
        return None
    
    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return the RGB color value."""
        state = self.coordinator.get_light_state(self._mesh_addr)
        if state:
            r = state.get('red')
            g = state.get('green')
            b = state.get('blue')
            if r is not None and g is not None and b is not None:
                return (r, g, b)
        return None
    
    @property
    def color_temp_kelvin(self) -> int | None:
        """Return the color temperature in Kelvin."""
        state = self.coordinator.get_light_state(self._mesh_addr)
        if state and state.get('color_temp') is not None:
            # Convert 0-100 (warm-cool) to Kelvin
            # 0 = warm = 2700K, 100 = cool = 6500K
            ct_pct = state['color_temp']
            kelvin = 2700 + int(ct_pct * (6500 - 2700) / 100)
            return kelvin
        return None
    
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        _LOGGER.debug("Turn on light %d with kwargs: %s", self._mesh_addr, kwargs)
        
        # Handle brightness
        if ATTR_BRIGHTNESS in kwargs:
            brightness = kwargs[ATTR_BRIGHTNESS]
            await self.coordinator.async_set_brightness(self._mesh_addr, brightness)
        
        # Handle RGB color
        if ATTR_RGB_COLOR in kwargs:
            r, g, b = kwargs[ATTR_RGB_COLOR]
            await self.coordinator.async_set_rgb(self._mesh_addr, r, g, b)
            self._attr_color_mode = ColorMode.RGB
        
        # Handle color temperature
        elif ATTR_COLOR_TEMP_KELVIN in kwargs:
            kelvin = kwargs[ATTR_COLOR_TEMP_KELVIN]
            # Convert Kelvin to 0-100 (warm-cool)
            # 2700K = 0 (warm), 6500K = 100 (cool)
            ct_pct = int((kelvin - 2700) * 100 / (6500 - 2700))
            ct_pct = max(0, min(100, ct_pct))
            await self.coordinator.async_set_color_temp(self._mesh_addr, ct_pct)
            self._attr_color_mode = ColorMode.COLOR_TEMP
        
        # If no specific attributes, just turn on
        if not any(k in kwargs for k in [ATTR_BRIGHTNESS, ATTR_RGB_COLOR, ATTR_COLOR_TEMP_KELVIN]):
            await self.coordinator.async_turn_on(self._mesh_addr)
        
        # Update state
        self.async_write_ha_state()
    
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        _LOGGER.debug("Turn off light %d", self._mesh_addr)
        await self.coordinator.async_turn_off(self._mesh_addr)
        self.async_write_ha_state()
    
    async def async_update(self) -> None:
        """Fetch new state data for this light."""
        await self.coordinator.async_query_status(self._mesh_addr)
