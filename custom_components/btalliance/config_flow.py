"""Config flow for BTAlliance Mesh Lights integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    DEFAULT_MESH_NAME,
    DEFAULT_PASSWORD,
    CONF_MESH_NAME,
    CONF_PASSWORD,
    CONF_GATEWAY_ADDRESS,
    FULIFE_MAC_PREFIXES,
)

_LOGGER = logging.getLogger(__name__)


def is_fulife_device(service_info: BluetoothServiceInfoBleak) -> bool:
    """Check if a BLE device is a Fulife mesh light."""
    # Check local name
    if service_info.name and service_info.name.startswith("Fulife"):
        return True
    
    # Check MAC prefix
    mac = service_info.address.upper()
    for prefix in FULIFE_MAC_PREFIXES:
        if mac.startswith(prefix):
            return True
    
    # Check advertisement data for "Fulife" string
    if service_info.manufacturer_data:
        for data in service_info.manufacturer_data.values():
            if b"Fulife" in data:
                return True
    
    return False


def mac_to_int(mac: str) -> int:
    """Convert MAC address string to integer."""
    mac_clean = mac.replace(":", "").replace("-", "")
    return int(mac_clean, 16)


class BTAllianceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BTAlliance Mesh Lights."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_device: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle bluetooth discovery."""
        _LOGGER.debug("Bluetooth discovery: %s (%s)", discovery_info.name, discovery_info.address)
        
        if not is_fulife_device(discovery_info):
            return self.async_abort(reason="not_supported")
        
        # If ANY BTAlliance mesh hub is already configured, assume all Fulife devices
        # in range are part of that mesh and don't show them as new config options.
        # This prevents mesh member lights from triggering new config flows.
        existing_entries = self._async_current_entries()
        if existing_entries:
            _LOGGER.debug(
                "Device %s ignored - mesh hub already configured (%d entries)", 
                discovery_info.address, 
                len(existing_entries)
            )
            return self.async_abort(reason="already_configured")
        
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        
        self._discovered_device = discovery_info
        
        # Show confirmation form with pre-filled defaults
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm bluetooth discovery."""
        if self._discovered_device is None:
            return self.async_abort(reason="not_supported")
        
        if user_input is not None:
            # User confirmed - create entry
            mesh_name = user_input.get(CONF_MESH_NAME, DEFAULT_MESH_NAME)
            password = user_input.get(CONF_PASSWORD, DEFAULT_PASSWORD)
            
            return self.async_create_entry(
                title=f"{mesh_name} Mesh ({self._discovered_device.address})",
                data={
                    CONF_GATEWAY_ADDRESS: mac_to_int(self._discovered_device.address),
                    CONF_MESH_NAME: mesh_name,
                    CONF_PASSWORD: password,
                },
            )
        
        # Show form with defaults
        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema({
                vol.Required(CONF_MESH_NAME, default=DEFAULT_MESH_NAME): str,
                vol.Required(CONF_PASSWORD, default=DEFAULT_PASSWORD): str,
            }),
            description_placeholders={
                "name": self._discovered_device.name or "Fulife Light",
                "address": self._discovered_device.address,
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle user-initiated setup."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            # Validate and create entry
            mesh_name = user_input[CONF_MESH_NAME]
            password = user_input[CONF_PASSWORD]
            
            # Check if we have a selected device or need to scan
            if CONF_ADDRESS in user_input:
                address = user_input[CONF_ADDRESS]
                gateway_address = mac_to_int(address)
                
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                
                return self.async_create_entry(
                    title=f"{mesh_name} Mesh ({address})",
                    data={
                        CONF_GATEWAY_ADDRESS: gateway_address,
                        CONF_MESH_NAME: mesh_name,
                        CONF_PASSWORD: password,
                    },
                )
            else:
                # No device selected, show device picker
                return await self.async_step_pick_device(user_input)
        
        # First step - show mesh credentials form
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_MESH_NAME, default=DEFAULT_MESH_NAME): str,
                vol.Required(CONF_PASSWORD, default=DEFAULT_PASSWORD): str,
            }),
            errors=errors,
        )

    async def async_step_pick_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle device selection."""
        errors: dict[str, str] = {}
        
        if user_input is not None and CONF_ADDRESS in user_input:
            address = user_input[CONF_ADDRESS]
            mesh_name = user_input.get(CONF_MESH_NAME, DEFAULT_MESH_NAME)
            password = user_input.get(CONF_PASSWORD, DEFAULT_PASSWORD)
            
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            
            return self.async_create_entry(
                title=f"{mesh_name} Mesh ({address})",
                data={
                    CONF_GATEWAY_ADDRESS: mac_to_int(address),
                    CONF_MESH_NAME: mesh_name,
                    CONF_PASSWORD: password,
                },
            )
        
        # Scan for Fulife devices
        self._discovered_devices = {}
        
        # Get all bluetooth devices
        service_infos = bluetooth.async_discovered_service_info(self.hass)
        
        for service_info in service_infos:
            if is_fulife_device(service_info):
                # Check if already configured
                if not self._async_is_address_configured(service_info.address):
                    self._discovered_devices[service_info.address] = service_info
        
        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")
        
        # Build device selection list
        device_options = {
            address: f"{info.name or 'Fulife Light'} ({address})"
            for address, info in self._discovered_devices.items()
        }
        
        # Get mesh credentials from previous step
        mesh_name = user_input.get(CONF_MESH_NAME, DEFAULT_MESH_NAME) if user_input else DEFAULT_MESH_NAME
        password = user_input.get(CONF_PASSWORD, DEFAULT_PASSWORD) if user_input else DEFAULT_PASSWORD
        
        return self.async_show_form(
            step_id="pick_device",
            data_schema=vol.Schema({
                vol.Required(CONF_ADDRESS): vol.In(device_options),
                vol.Required(CONF_MESH_NAME, default=mesh_name): str,
                vol.Required(CONF_PASSWORD, default=password): str,
            }),
            errors=errors,
        )

    @callback
    def _async_is_address_configured(self, address: str) -> bool:
        """Check if address is already configured as unique_id or gateway."""
        address_int = mac_to_int(address)
        for entry in self._async_current_entries():
            # Check if this is the unique_id
            if entry.unique_id == address:
                return True
            # Check if this is a configured gateway address
            if entry.data.get(CONF_GATEWAY_ADDRESS) == address_int:
                return True
        return False

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return BTAllianceOptionsFlow(config_entry)


class BTAllianceOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for BTAlliance."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_MESH_NAME,
                    default=self.config_entry.data.get(CONF_MESH_NAME, DEFAULT_MESH_NAME),
                ): str,
                vol.Required(
                    CONF_PASSWORD,
                    default=self.config_entry.data.get(CONF_PASSWORD, DEFAULT_PASSWORD),
                ): str,
            }),
        )
