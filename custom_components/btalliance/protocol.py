"""Protocol layer for Telink BLE Mesh command/response handling."""

import datetime
import logging
from typing import Optional

from .const import (
    COMMAND_ON_OFF, COMMAND_SET_LUMINANCE, COMMAND_SET_RGB_LUM,
    COMMAND_SET_CT_LUM, COMMAND_QUERY_STATUS, COMMAND_SET_DATETIME,
    NOTIFY_STATUS_RESPONSE, NOTIFY_LIGHT_STATUS,
    MODE_RGB, MODE_COLOR_TEMP, VENDOR_ID, BROADCAST_ADDRESS
)
from .crypto import TelinkCrypto

_LOGGER = logging.getLogger(__name__)


class TelinkProtocol:
    """Handles Telink BLE Mesh protocol packet construction and parsing."""
    
    def __init__(self, mac_bytes: bytes, mesh_name: str, password: str):
        """Initialize protocol handler."""
        self.mac_bytes = mac_bytes
        self.mesh_name_bytes = TelinkCrypto.pad_string(mesh_name, 16)
        self.mesh_password_bytes = TelinkCrypto.pad_string(password, 16)
        self.session_key: Optional[bytearray] = None
        self.sequence_number = 1
        self.target_address = (0x0001).to_bytes(2, "little")
    
    def set_target_address(self, mesh_addr: int) -> None:
        """Set target mesh address for commands."""
        self.target_address = mesh_addr.to_bytes(2, "little")
    
    def get_target_address(self) -> int:
        """Get current target mesh address."""
        return int.from_bytes(self.target_address, "little")
    
    def _next_sequence(self) -> int:
        """Increment and return sequence number."""
        self.sequence_number += 1
        if self.sequence_number == 0:
            self.sequence_number = 1
        return self.sequence_number
    
    def _build_command_frame(self, opcode: int) -> bytearray:
        """Build base command frame."""
        seq = self._next_sequence()
        seq_bytes = seq.to_bytes(3, "big")
        
        data = bytearray(20)
        data[0:3] = seq_bytes
        data[5] = self.target_address[0]
        data[6] = self.target_address[1]
        data[7] = opcode
	data[8] = (VENDOR_ID >> 8) & 0xFF
	data[9] = VENDOR_ID & 0xFF
        return data
    
    def _encrypt_command(self, data: bytearray) -> bytearray:
        """Encrypt command data for transmission."""
        if self.session_key is None:
            raise RuntimeError("Session key not established")
        nonce = TelinkCrypto.get_nonce_ivm(self.mac_bytes, self.sequence_number)
        return TelinkCrypto.encrypt_command(self.session_key, nonce, data)
    
    def generate_login_payload(self, session_random: bytes) -> bytearray:
        """Generate encrypted login payload."""
        plaintext = bytearray(16)
        for i in range(16):
            plaintext[i] = self.mesh_name_bytes[i] ^ self.mesh_password_bytes[i]
        
        sk = bytearray(16)
        sk[:8] = session_random
        
        encrypted = TelinkCrypto.encrypt(sk, bytes(plaintext))
        
        payload = bytearray(16)
        payload[0:8] = session_random
        payload[8:16] = encrypted[8:16][::-1]
        return payload
    
    def process_login_response(self, response: bytes, session_random: bytes) -> bool:
        """Process login response and derive session key."""
        if len(response) < 17 or response[0] != 0x0D:
            return False
        
        sk = bytearray(response[1:17])
        rands = bytearray(response[1:9])
        
        self.session_key = TelinkCrypto.derive_session_key(
            self.mesh_name_bytes,
            self.mesh_password_bytes,
            session_random,
            rands,
            sk
        )
        return self.session_key is not None
    
    def generate_on_off_command(self, state: bool) -> bytearray:
        """Generate ON/OFF command."""
        data = self._build_command_frame(COMMAND_ON_OFF)
        data[10] = 0x01 if state else 0x00
        return self._encrypt_command(data)
    
    def generate_luminance_command(self, level: int) -> bytearray:
        """Generate luminance command (0-100)."""
        data = self._build_command_frame(COMMAND_SET_LUMINANCE)
        data[10] = max(0, min(100, level))
        return self._encrypt_command(data)
    
    def generate_rgb_command(self, red: int, green: int, blue: int) -> bytearray:
        """Generate RGB color command."""
        data = self._build_command_frame(COMMAND_SET_RGB_LUM)
        data[10] = MODE_RGB
        data[11] = max(0, min(255, red))
        data[12] = max(0, min(255, green))
        data[13] = max(0, min(255, blue))
        return self._encrypt_command(data)
    
    def generate_color_temp_command(self, color_temp: int) -> bytearray:
        """Generate color temperature command (0=warm, 100=cool)."""
        data = self._build_command_frame(COMMAND_SET_CT_LUM)
        data[10] = MODE_COLOR_TEMP
        data[11] = max(0, min(100, color_temp))
        return self._encrypt_command(data)
    
    def generate_query_status_command(self) -> bytearray:
        """Generate status query command."""
        data = self._build_command_frame(COMMAND_QUERY_STATUS)
        data[10] = 0x01
        return self._encrypt_command(data)
    
    def generate_datetime_command(self) -> bytearray:
        """Generate set datetime command (broadcast)."""
        original_addr = self.target_address
        self.target_address = BROADCAST_ADDRESS.to_bytes(2, "little")
        
        now = datetime.datetime.now()
        data = self._build_command_frame(COMMAND_SET_DATETIME)
        data[10] = now.year & 0xFF
        data[11] = (now.year >> 8) & 0xFF
        data[12] = now.month
        data[13] = now.day
        data[14] = now.hour
        data[15] = now.minute
        data[16] = now.second
        
        result = self._encrypt_command(data)
        self.target_address = original_addr
        return result
    
    def parse_notification(self, data: bytearray) -> Optional[dict]:
        """Parse and decrypt notification data."""
        if self.session_key is None:
            return None
        
        nonce = TelinkCrypto.get_nonce_ivs(self.mac_bytes)
        nonce[3:8] = data[0:5]
        
        try:
            decrypted = TelinkCrypto.decrypt_response(self.session_key, nonce, data)
        except Exception:
            return None
        
        if decrypted is None:
            return None
        
        opcode = decrypted[7]
        result = {'opcode': opcode, 'raw': decrypted}
        
        if opcode == NOTIFY_STATUS_RESPONSE:
            result['red'] = decrypted[10]
            result['green'] = decrypted[11]
            result['blue'] = decrypted[12]
            result['color_temp'] = decrypted[13]
            result['warm'] = decrypted[14]
            result['cool'] = decrypted[15]
            result['luminance'] = decrypted[16]
            result['is_on'] = result['luminance'] > 0 or result['warm'] > 0 or result['cool'] > 0
            
        elif opcode == NOTIFY_LIGHT_STATUS:
            light_addr = decrypted[10]
            lum_byte = decrypted[12]
            is_on = lum_byte not in (0x00, 0xFF)
            luminance = lum_byte if lum_byte != 0xFF else 0
            
            result['light_addr'] = light_addr
            result['is_on'] = is_on
            result['luminance'] = luminance
        
        return result
