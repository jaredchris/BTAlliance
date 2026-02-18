"""Constants for BTAlliance Mesh Lights integration."""

from typing import Final
from uuid import UUID

DOMAIN: Final = "btalliance"

# Default mesh credentials
DEFAULT_MESH_NAME: Final = "Fulife"
DEFAULT_PASSWORD: Final = "2846"

# Standard Telink BLE Mesh UUIDs
SERVICE_UUID: Final = UUID("00010203-0405-0607-0809-0a0b0c0d1910")
START_SESSION_UUID: Final = UUID("00010203-0405-0607-0809-0a0b0c0d1914")
NOTIFY_UUID: Final = UUID("00010203-0405-0607-0809-0a0b0c0d1911")
COMMAND_UUID: Final = UUID("00010203-0405-0607-0809-0a0b0c0d1912")

# Command opcodes
COMMAND_ON_OFF: Final = 0xD0
COMMAND_SET_LUMINANCE: Final = 0xD2
COMMAND_SET_RGB_LUM: Final = 0xE2
COMMAND_SET_CT_LUM: Final = 0xE2
COMMAND_QUERY_STATUS: Final = 0xDA
COMMAND_SET_DATETIME: Final = 0xE4

# Notification opcodes
NOTIFY_LIGHT_STATUS: Final = 0xDC
NOTIFY_STATUS_RESPONSE: Final = 0xDB

# Command mode bytes
MODE_RGB: Final = 0x04
MODE_COLOR_TEMP: Final = 0x05

# Vendor ID
VENDOR_ID: Final = 0x1102

# Mesh addresses
BROADCAST_ADDRESS: Final = 0xFFFF
DEFAULT_MESH_ADDRESS: Final = 0x0001

# Connection parameters
MAX_CONNECTION_RETRIES: Final = 30
CONNECTION_TIMEOUT: Final = 1.5
LOGIN_TIMEOUT: Final = 1.0
DISCONNECT_TIMEOUT: Final = 0.3
RETRY_DELAY: Final = 0.1

# Mesh discovery
MESH_DISCOVERY_TIMEOUT: Final = 5.0  # seconds to wait for mesh device discovery

# Config flow
CONF_MESH_NAME: Final = "mesh_name"
CONF_PASSWORD: Final = "password"
CONF_GATEWAY_ADDRESS: Final = "gateway_address"

# BLE advertisement matching
FULIFE_MAC_PREFIXES: Final = ["FF:00:06:0E", "FF:05:01:0B"]
