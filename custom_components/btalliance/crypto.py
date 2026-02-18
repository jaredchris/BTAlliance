"""Cryptographic functions for Telink BLE Mesh protocol."""

import logging
from typing import Optional
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

_LOGGER = logging.getLogger(__name__)


class TelinkCrypto:
    """Telink BLE Mesh cryptographic operations."""
    
    @staticmethod
    def pad_string(string: str, length: int) -> bytes:
        """Pad string to specified length with null bytes."""
        bytes_data = string.encode('utf-8')
        return bytes_data[:length].ljust(length, b'\x00')
    
    @staticmethod
    def reverse(arr: bytes, begin: int, end: int) -> bytes:
        """Reverse bytes in array between begin and end indices."""
        arr = bytearray(arr)
        while begin < end:
            arr[begin], arr[end] = arr[end], arr[begin]
            begin += 1
            end -= 1
        return bytes(arr)
    
    @staticmethod
    def encrypt(key: bytes, content: bytes) -> bytearray:
        """AES-ECB encrypt with reversed key and content."""
        reversed_key = key[::-1]
        reversed_content = content[::-1]
        cipher = Cipher(algorithms.AES(reversed_key), modes.ECB(), backend=default_backend())
        encryptor = cipher.encryptor()
        encrypted = encryptor.update(reversed_content) + encryptor.finalize()
        return bytearray(encrypted)
    
    @staticmethod
    def decrypt(key: bytes, content: bytes) -> bytearray:
        """AES-ECB decrypt with reversed key and content."""
        reversed_key = key[::-1]
        reversed_content = content[::-1]
        cipher = Cipher(algorithms.AES(reversed_key), modes.ECB(), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(reversed_content) + decryptor.finalize()
        return bytearray(decrypted)
    
    @staticmethod
    def aes_att_encryption(key: bytes, content: bytes) -> bytearray:
        """AES ATT encryption (encrypt and reverse result)."""
        try:
            result = TelinkCrypto.encrypt(key, content)
            return bytearray(result[::-1])
        except Exception as e:
            _LOGGER.error("AES encryption error: %s", e)
            return None
    
    @staticmethod
    def aes_att_decryption(key: bytes, content: bytes) -> bytearray:
        """AES ATT decryption (decrypt and reverse result)."""
        try:
            result = TelinkCrypto.decrypt(key, content)
            return bytearray(result[::-1])
        except Exception as e:
            _LOGGER.error("AES decryption error: %s", e)
            return None
    
    @staticmethod
    def derive_session_key(mesh_name: bytes, password: bytes, 
                           randm: bytes, rands: bytes, sk: bytes) -> Optional[bytearray]:
        """Derive session key from mesh credentials and random values."""
        key = bytes(randm[:8]) + bytes(rands[:8])
        plaintext = bytes([mesh_name[i] ^ password[i] for i in range(16)])
        return TelinkCrypto.aes_att_encryption(plaintext, key)
    
    @staticmethod
    def get_nonce_ivs(mac_address: bytes) -> bytearray:
        """Get nonce IV for slave (notification decryption)."""
        ivs = bytearray(8)
        ivs[0:3] = mac_address[0:3]
        return ivs
    
    @staticmethod
    def get_nonce_ivm(mac_address: bytes, sequence_number: int) -> bytearray:
        """Get nonce IV for master (command encryption)."""
        sn_bytes = sequence_number.to_bytes(6, "little")
        ivm = bytearray(8)
        ivm[0:4] = mac_address[0:4]
        ivm[4] = 1
        ivm[5] = sn_bytes[2]
        ivm[6] = sn_bytes[1]
        ivm[7] = sn_bytes[0]
        return ivm
    
    @staticmethod
    def encrypt_command(key: bytes, iv: bytearray, data: bytearray) -> bytearray:
        """Encrypt command data with MIC calculation."""
        mic_len = 2
        mic_index = 3
        ps_index = 5
        length = 15
        
        r = bytearray(16)
        e = bytearray(16)
        
        r[:8] = iv[:8]
        r[8] = length & 0xFF
        r = TelinkCrypto.aes_att_encryption(key, bytes(r))
        
        for i in range(length):
            r[i & 15] ^= data[i + ps_index]
            if i == length - 1:
                r = TelinkCrypto.aes_att_encryption(key, r)
        
        for i in range(mic_len):
            data[i + mic_index] = r[i]
        
        r = bytearray(16)
        r[1:9] = iv[:8]
        for i in range(length):
            if (i & 15) == 0:
                e = TelinkCrypto.aes_att_encryption(key, r)
                r[0] += 1
            data[i + ps_index] ^= e[i & 15]
        
        return data
    
    @staticmethod
    def decrypt_response(key: bytearray, iv: bytearray, data: bytearray) -> Optional[bytearray]:
        """Decrypt notification response with MIC verification."""
        ps_index = 7
        length = 13
        mic_index = 5
        mic_len = 2
        
        r = bytearray(16)
        e = bytearray(16)
        
        r[1:9] = iv[:8]
        for i in range(length):
            if (i & 15) == 0:
                e = TelinkCrypto.aes_att_encryption(key, r)
                r[0] += 1
            data[i + ps_index] ^= e[i & 15]
        
        r = bytearray(16)
        r[:8] = iv[:8]
        r[8] = length & 0xFF
        r = TelinkCrypto.aes_att_encryption(key, r)
        
        for i in range(length):
            r[i & 15] ^= data[i + ps_index]
            if (i & 15) == 15 or i == length - 1:
                r = TelinkCrypto.aes_att_encryption(key, r)
        
        for i in range(mic_len):
            if data[i + mic_index] != r[i]:
                _LOGGER.debug("MIC verification failed")
                return None
        
        return data
