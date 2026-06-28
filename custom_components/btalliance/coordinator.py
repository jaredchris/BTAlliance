"""Coordinator for BTAlliance mesh device management."""

import asyncio
import logging
import os
import time
from typing import Any, Callable, Dict, Optional

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from bleak_retry_connector import establish_connection, BleakClientWithServiceCache
from bleak import BleakClient
from bleak.exc import BleakError

from datetime import timedelta

from .const import (
    DOMAIN,
    SERVICE_UUID, START_SESSION_UUID, NOTIFY_UUID, COMMAND_UUID,
    NOTIFY_STATUS_RESPONSE, NOTIFY_LIGHT_STATUS,
    MAX_CONNECTION_RETRIES, CONNECTION_TIMEOUT, LOGIN_TIMEOUT,
    DISCONNECT_TIMEOUT, RETRY_DELAY, MESH_DISCOVERY_TIMEOUT,
    BROADCAST_ADDRESS, POLLING_INTERVAL,
)
from .protocol import TelinkProtocol

_LOGGER = logging.getLogger(__name__)

# UUID strings for bleak
SERVICE_UUID_STR = "00010203-0405-0607-0809-0a0b0c0d1910"
START_SESSION_UUID_STR = "00010203-0405-0607-0809-0a0b0c0d1914"
NOTIFY_UUID_STR = "00010203-0405-0607-0809-0a0b0c0d1911"
COMMAND_UUID_STR = "00010203-0405-0607-0809-0a0b0c0d1912"


class BTAllianceMeshCoordinator(DataUpdateCoordinator):
    """Coordinator for managing BTAlliance mesh network."""
    
    def __init__(
        self,
        hass: HomeAssistant,
        gateway_address: int,
        mesh_name: str,
        password: str,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=POLLING_INTERVAL),
        )
        
        self.gateway_address = gateway_address
        self.mesh_name = mesh_name
        self.password = password
        self.mac_bytes = gateway_address.to_bytes(6, "little")
        
        # Protocol handler
        self.protocol = TelinkProtocol(self.mac_bytes, mesh_name, password)
        
        # Connection state
        self.connected = False
        self.login_valid = False
        self.ble_device = None
        self.client = None
        self.start_session_handle: Optional[int] = None
        self.notify_handle: Optional[int] = None
        self.command_handle: Optional[int] = None
        
        # Mesh devices discovered via 0xDC notifications
        self.discovered_devices: Dict[int, Dict[str, Any]] = {}
        
        # Light state cache per mesh address
        self.light_states: Dict[int, Dict[str, Any]] = {}
        
        # Callbacks for state updates
        self._state_callbacks: Dict[int, Callable] = {}
        
        # Discovery event
        self._discovery_complete = asyncio.Event()
        
        # Callback for adding new entities dynamically
        self._new_device_callback: Optional[Callable[[int], None]] = None
        
        
    
    def set_new_device_callback(self, callback: Callable[[int], None]) -> None:
        """Set callback to be called when new mesh devices are discovered."""
        self._new_device_callback = callback
    
    def register_state_callback(self, mesh_addr: int, callback: Callable) -> None:
        """Register callback for state updates for a specific mesh address."""
        self._state_callbacks[mesh_addr] = callback
    
    def unregister_state_callback(self, mesh_addr: int) -> None:
        """Unregister state callback."""
        self._state_callbacks.pop(mesh_addr, None)
    
    def _notify_state_change(self, mesh_addr: int) -> None:
        """Notify registered callback of state change."""
        if mesh_addr in self._state_callbacks:
            self._state_callbacks[mesh_addr]()
        # Also notify broadcast listeners
        if BROADCAST_ADDRESS in self._state_callbacks:
            self._state_callbacks[BROADCAST_ADDRESS]()
    
    def _process_notification(self, data: bytearray) -> None:
        """Process incoming notification data."""
        parsed = self.protocol.parse_notification(data)
        if parsed is None:
            return
        
        opcode = parsed['opcode']
        
        if opcode == NOTIFY_STATUS_RESPONSE:
            # Full status response (0xDB) - update state for current target
            target_addr = self.protocol.get_target_address()
            self.light_states[target_addr] = {
                'is_on': parsed['is_on'],
                'luminance': parsed['luminance'],
                'red': parsed['red'],
                'green': parsed['green'],
                'blue': parsed['blue'],
                'color_temp': parsed['color_temp'],
                'warm': parsed['warm'],
                'cool': parsed['cool'],
                'last_seen': time.time(),
            }
            _LOGGER.debug("0xDB status for addr %d: on=%s lum=%d RGB=(%d,%d,%d)",
                         target_addr, parsed['is_on'], parsed['luminance'],
                         parsed['red'], parsed['green'], parsed['blue'])
            self._notify_state_change(target_addr)
            
        elif opcode == NOTIFY_LIGHT_STATUS:
            # Mesh broadcast status (0xDC)
            light_addr = parsed['light_addr']
            is_on = parsed['is_on']
            luminance = parsed['luminance']
            
            # Check if this is a new device
            is_new_device = light_addr not in self.discovered_devices
            
            # Track discovered device
            self.discovered_devices[light_addr] = {
                'is_on': is_on,
                'luminance': luminance,
                'last_seen': time.time()
            }
            
            # Update light state if we have it
            if light_addr in self.light_states:
                self.light_states[light_addr]['is_on'] = is_on
                self.light_states[light_addr]['luminance'] = luminance
                self.light_states[light_addr]['last_seen'] = time.time()
            else:
                self.light_states[light_addr] = {
                    'is_on': is_on,
                    'luminance': luminance,
                    'last_seen': time.time(),
                }
            
            _LOGGER.debug("0xDC mesh: light=%d %s lum=%d (total: %d devices)",
                         light_addr, "ON" if is_on else "OFF", luminance,
                         len(self.discovered_devices))
            
            # Notify about new device discovery
            if is_new_device and self._new_device_callback:
                _LOGGER.info("New mesh device discovered: %d", light_addr)
                self._new_device_callback(light_addr)
            
            self._notify_state_change(light_addr)
    
    async def async_connect(self) -> bool:
        """Connect to the gateway device and establish session."""
        mac_str = self._format_mac(self.gateway_address)
        _LOGGER.info("Connecting to gateway: %s", mac_str)
        
        # Find the BLE device using HA's bluetooth integration
        self.ble_device = async_ble_device_from_address(
            self.hass, 
            mac_str,
            connectable=True
        )
        
        if self.ble_device is None:
            _LOGGER.error("Gateway device not found: %s", mac_str)
            return False
        
        _LOGGER.debug("Found BLE device: %s", self.ble_device)
        
        try:
            # Use bleak_retry_connector for robust connection via ESPHome proxy
            self.client = await establish_connection(
                BleakClientWithServiceCache,
                self.ble_device,
                mac_str,
                disconnected_callback=self._on_disconnect,
            )
            self.connected = True
            _LOGGER.info("Connected to gateway: %s", self.ble_device.address)
        except BleakError as e:
            _LOGGER.error("Failed to connect to gateway: %s", e)
            return False
        except Exception as e:
            _LOGGER.error("Unexpected connection error: %s", e)
            return False
        
        # Login
        try:
            session_random = bytearray(os.urandom(8))
            
            login_data = bytearray(17)
            login_data[0] = 0x0C
            login_payload = self.protocol.generate_login_payload(session_random)
            login_data[1:17] = login_payload
            
            _LOGGER.debug("Sending login request...")
            await self.client.write_gatt_char(START_SESSION_UUID_STR, bytes(login_data))
            await asyncio.sleep(0.1)
            
            # Read response
            response = await self.client.read_gatt_char(START_SESSION_UUID_STR)
            _LOGGER.debug("Login response: %s", response.hex() if response else "None")
            
            self.login_valid = self.protocol.process_login_response(response, session_random)
            
            if not self.login_valid:
                _LOGGER.error("Login failed - invalid response")
                return False
            
            _LOGGER.info("Login successful to gateway %s", self.ble_device.address)
            
        except Exception as e:
            _LOGGER.error("Login error: %s", e)
            import traceback
            _LOGGER.debug(traceback.format_exc())
            return False
        
        # Setup notifications
        try:
            _LOGGER.debug("Enabling notifications...")
            await self.client.start_notify(NOTIFY_UUID_STR, self._on_notification)
            await self.client.write_gatt_char(NOTIFY_UUID_STR, bytes([0x01]))
            _LOGGER.debug("Notifications enabled")
        except Exception as e:
            _LOGGER.warning("Failed to enable notifications: %s", e)
        
        # Send datetime command
        try:
            datetime_cmd = self.protocol.generate_datetime_command()
            await self.client.write_gatt_char(COMMAND_UUID_STR, bytes(datetime_cmd))
            _LOGGER.debug("DateTime command sent")
        except Exception as e:
            _LOGGER.warning("Failed to send datetime: %s", e)
        
        return True
    
    def _on_disconnect(self, client: BleakClient) -> None:
        """Handle disconnection."""
        _LOGGER.warning("Disconnected from gateway")
        self.connected = False
        self.login_valid = False
    
    def _on_notification(self, sender, data: bytearray) -> None:
        """Handle incoming BLE notification."""
        _LOGGER.debug("Notification received: %s", data.hex() if data else "None")
        self._process_notification(bytearray(data))
    
    async def async_disconnect(self) -> None:
        """Disconnect from gateway."""
        if self.client and self.client.is_connected:
            await self.client.disconnect()
        self.connected = False
        self.login_valid = False
        _LOGGER.debug("Disconnected from gateway")
    
    async def async_discover_mesh_devices(self, timeout: float = MESH_DISCOVERY_TIMEOUT) -> Dict[int, Dict]:
        """Discover mesh devices by sending broadcast and waiting for 0xDC responses."""
        if not self.login_valid:
            _LOGGER.error("Cannot discover - not logged in")
            return {}
        
        _LOGGER.info("Starting mesh device discovery (timeout=%.1fs)...", timeout)
        
        # Don't clear - keep devices discovered during connection
        
        # Send broadcast query status command to trigger 0xDC responses
        self.protocol.set_target_address(BROADCAST_ADDRESS)
        
        try:
            # Send multiple query commands to ensure all devices respond
            for i in range(3):
                query_cmd = self.protocol.generate_query_status_command()
                _LOGGER.debug("Sending broadcast query command %d/3...", i + 1)
                await self.client.write_gatt_char(COMMAND_UUID_STR, bytes(query_cmd))
                await asyncio.sleep(1.0)  # Wait between commands
            
            # Wait additional time for responses
            remaining = timeout - 3.0
            if remaining > 0:
                _LOGGER.debug("Waiting %.1fs for mesh responses...", remaining)
                await asyncio.sleep(remaining)
                
        except Exception as e:
            _LOGGER.error("Discovery command failed: %s", e)
            import traceback
            _LOGGER.debug(traceback.format_exc())
        
        _LOGGER.info("Discovered %d mesh devices: %s", 
                    len(self.discovered_devices), 
                    list(self.discovered_devices.keys()))
        
        return self.discovered_devices.copy()
    
    async def async_send_command(self, mesh_addr: int, command_data: bytearray) -> bool:
        """Send command to specific mesh address."""
        if not self.login_valid:
            _LOGGER.error("Cannot send command - not logged in")
            return False
        
        self.protocol.set_target_address(mesh_addr)
        
        try:
            await self.client.write_gatt_char(COMMAND_UUID_STR, bytes(command_data))
            return True
        except Exception as e:
            _LOGGER.error("Command send failed: %s", e)
        
        return False
    
    async def async_turn_on(self, mesh_addr: int) -> bool:
        """Turn on light at mesh address."""
        self.protocol.set_target_address(mesh_addr)
        cmd = self.protocol.generate_on_off_command(True)
        return await self.async_send_command(mesh_addr, cmd)
    
    async def async_turn_off(self, mesh_addr: int) -> bool:
        """Turn off light at mesh address."""
        self.protocol.set_target_address(mesh_addr)
        cmd = self.protocol.generate_on_off_command(False)
        return await self.async_send_command(mesh_addr, cmd)
    
    async def async_set_brightness(self, mesh_addr: int, brightness: int) -> bool:
        """Set brightness (0-255 HA scale, converted to 0-100)."""
        level = int(brightness * 100 / 255)
        self.protocol.set_target_address(mesh_addr)
        cmd = self.protocol.generate_luminance_command(level)
        return await self.async_send_command(mesh_addr, cmd)
    
    async def async_set_rgb(self, mesh_addr: int, red: int, green: int, blue: int) -> bool:
        """Set RGB color."""
        self.protocol.set_target_address(mesh_addr)
        cmd = self.protocol.generate_rgb_command(red, green, blue)
        return await self.async_send_command(mesh_addr, cmd)
    
    async def async_set_color_temp(self, mesh_addr: int, color_temp_pct: int) -> bool:
        """Set color temperature (0=warm, 100=cool)."""
        self.protocol.set_target_address(mesh_addr)
        cmd = self.protocol.generate_color_temp_command(color_temp_pct)
        return await self.async_send_command(mesh_addr, cmd)
    
    async def async_query_status(self, mesh_addr: int) -> bool:
        """Query status of specific device."""
        self.protocol.set_target_address(mesh_addr)
        cmd = self.protocol.generate_query_status_command()
        return await self.async_send_command(mesh_addr, cmd)

    async def async_broadcast_turn_on(self) -> bool:
        """Turn on all lights via mesh broadcast."""
        return await self.async_turn_on(BROADCAST_ADDRESS)

    async def async_broadcast_turn_off(self) -> bool:
        """Turn off all lights via mesh broadcast."""
        return await self.async_turn_off(BROADCAST_ADDRESS)

    async def async_broadcast_set_brightness(self, brightness: int) -> bool:
        """Set brightness for all lights via mesh broadcast."""
        return await self.async_set_brightness(BROADCAST_ADDRESS, brightness)

    async def async_broadcast_set_rgb(self, red: int, green: int, blue: int) -> bool:
        """Set RGB color for all lights via mesh broadcast."""
        return await self.async_set_rgb(BROADCAST_ADDRESS, red, green, blue)

    async def async_broadcast_set_color_temp(self, color_temp_pct: int) -> bool:
        """Set color temperature for all lights via mesh broadcast."""
        return await self.async_set_color_temp(BROADCAST_ADDRESS, color_temp_pct)

    def get_light_state(self, mesh_addr: int) -> Optional[Dict[str, Any]]:
        """Get cached state for a light."""
        return self.light_states.get(mesh_addr)
    
    @staticmethod
    def _format_mac(address: int) -> str:
        """Format integer address as MAC string."""
        addr_hex = f"{address:012X}"
        return ':'.join([addr_hex[i:i+2] for i in range(0, 12, 2)])
    
    async def _async_update_data(self) -> Dict[int, Dict[str, Any]]:
        """Fetch data from mesh network via periodic broadcast query."""
        # Try to reconnect if not connected
        if not self.login_valid:
            _LOGGER.info("Not connected - attempting reconnection...")
            try:
                if await self.async_connect():
                    _LOGGER.info("Reconnection successful")
                else:
                    _LOGGER.warning("Reconnection failed - will retry next poll")
                    return self.light_states.copy()
            except Exception as e:
                _LOGGER.warning("Reconnection error: %s", e)
                return self.light_states.copy()
        
        _LOGGER.debug("Periodic status poll - sending broadcast query")
        
        # Send broadcast query to get status from all devices
        # This will trigger 0xDC notifications which update discovered_devices
        # and may discover new devices
        self.protocol.set_target_address(BROADCAST_ADDRESS)
        
        try:
            query_cmd = self.protocol.generate_query_status_command()
            await self.client.write_gatt_char(COMMAND_UUID_STR, bytes(query_cmd))
        except Exception as e:
            _LOGGER.warning("Periodic poll failed: %s - marking disconnected", e)
            self.login_valid = False
            self.connected = False
        
        return self.light_states.copy()
