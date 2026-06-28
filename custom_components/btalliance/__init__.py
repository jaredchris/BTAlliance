"""BTAlliance Mesh Lights integration for Home Assistant."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr

from .const import (
    DOMAIN,
    CONF_GATEWAY_ADDRESS,
    CONF_MESH_NAME,
    CONF_PASSWORD,
)
from .coordinator import BTAllianceMeshCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LIGHT]


BROADCAST_RGB_SCHEMA = vol.Schema({
    vol.Required("red"): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
    vol.Required("green"): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
    vol.Required("blue"): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
})

BROADCAST_BRIGHTNESS_SCHEMA = vol.Schema({
    vol.Required("brightness"): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
})

BROADCAST_COLOR_TEMP_SCHEMA = vol.Schema({
    vol.Required("color_temp_pct"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
})


async def _get_coordinator(
    hass: HomeAssistant,
    call: ServiceCall,
) -> BTAllianceMeshCoordinator:
    """Return the coordinator to use for a service call."""
    coordinators = hass.data.get(DOMAIN, {})

    if len(coordinators) == 1:
        return next(iter(coordinators.values()))

    entry_id = call.data.get("entry_id")
    if entry_id and entry_id in coordinators:
        return coordinators[entry_id]

    raise ValueError(
        "Multiple BTAlliance hubs are configured; provide entry_id."
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up BTAlliance Mesh Lights from a config entry."""
    _LOGGER.debug("Setting up BTAlliance entry: %s", entry.entry_id)

    gateway_address = entry.data[CONF_GATEWAY_ADDRESS]
    mesh_name = entry.data[CONF_MESH_NAME]
    password = entry.data[CONF_PASSWORD]

    coordinator = BTAllianceMeshCoordinator(
        hass=hass,
        gateway_address=gateway_address,
        mesh_name=mesh_name,
        password=password,
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"{mesh_name} Mesh Hub",
        manufacturer="BTAlliance/Fulife",
        model="Telink BLE Mesh Gateway",
    )

    if not hass.services.has_service(DOMAIN, "broadcast_turn_on"):

        async def handle_broadcast_turn_on(call: ServiceCall) -> None:
            coordinator = await _get_coordinator(hass, call)
            await coordinator.async_broadcast_turn_on()

        async def handle_broadcast_turn_off(call: ServiceCall) -> None:
            coordinator = await _get_coordinator(hass, call)
            await coordinator.async_broadcast_turn_off()

        async def handle_broadcast_set_brightness(call: ServiceCall) -> None:
            coordinator = await _get_coordinator(hass, call)
            await coordinator.async_broadcast_set_brightness(
                call.data["brightness"]
            )

        async def handle_broadcast_set_rgb(call: ServiceCall) -> None:
            coordinator = await _get_coordinator(hass, call)
            await coordinator.async_broadcast_set_rgb(
                call.data["red"],
                call.data["green"],
                call.data["blue"],
            )

        async def handle_broadcast_set_color_temp(call: ServiceCall) -> None:
            coordinator = await _get_coordinator(hass, call)
            await coordinator.async_broadcast_set_color_temp(
                call.data["color_temp_pct"]
            )

        hass.services.async_register(
            DOMAIN,
            "broadcast_turn_on",
            handle_broadcast_turn_on,
        )

        hass.services.async_register(
            DOMAIN,
            "broadcast_turn_off",
            handle_broadcast_turn_off,
        )

        hass.services.async_register(
            DOMAIN,
            "broadcast_set_brightness",
            handle_broadcast_set_brightness,
            schema=BROADCAST_BRIGHTNESS_SCHEMA,
        )

        hass.services.async_register(
            DOMAIN,
            "broadcast_set_rgb",
            handle_broadcast_set_rgb,
            schema=BROADCAST_RGB_SCHEMA,
        )

        hass.services.async_register(
            DOMAIN,
            "broadcast_set_color_temp",
            handle_broadcast_set_color_temp,
            schema=BROADCAST_COLOR_TEMP_SCHEMA,
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading BTAlliance entry: %s", entry.entry_id)

    unload_ok = await hass.config_entries.async_unload_platforms(
        entry,
        PLATFORMS,
    )

    if unload_ok:
        coordinator: BTAllianceMeshCoordinator = hass.data[DOMAIN].pop(
            entry.entry_id
        )
        await coordinator.async_disconnect()

    return unload_ok


async def async_reload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)