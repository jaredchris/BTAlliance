"""BTAlliance Mesh Lights integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, CONF_GATEWAY_ADDRESS, CONF_MESH_NAME, CONF_PASSWORD
from .coordinator import BTAllianceMeshCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LIGHT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up BTAlliance Mesh Lights from a config entry."""
    _LOGGER.debug("Setting up BTAlliance entry: %s", entry.entry_id)
    
    gateway_address = entry.data[CONF_GATEWAY_ADDRESS]
    mesh_name = entry.data[CONF_MESH_NAME]
    password = entry.data[CONF_PASSWORD]
    
    # Create coordinator
    coordinator = BTAllianceMeshCoordinator(
        hass=hass,
        gateway_address=gateway_address,
        mesh_name=mesh_name,
        password=password,
    )
    
    # Store coordinator
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator
    
    # Register the hub device FIRST before any child devices
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"{mesh_name} Mesh Hub",
        manufacturer="BTAlliance/Fulife",
        model="Telink BLE Mesh Gateway",
    )
    
    # Setup platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading BTAlliance entry: %s", entry.entry_id)
    
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        coordinator: BTAllianceMeshCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_disconnect()
    
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
