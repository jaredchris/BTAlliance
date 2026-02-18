# BTAlliance Mesh Lights

A Home Assistant custom integration for controlling BTAlliance/Fulife Telink BLE Mesh lights.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub Release](https://img.shields.io/github/v/release/YOUR_USERNAME/pyBTAlliance)](https://github.com/YOUR_USERNAME/pyBTAlliance/releases)

## Features

- **Auto-Discovery**: Automatically detects Fulife mesh lights via Bluetooth LE advertisements
- **Mesh Network Support**: Connect to one gateway light and control all lights on the mesh
- **Full Light Control**:
  - On/Off
  - Brightness (0-100%)
  - RGB Color
  - Color Temperature (warm to cool white)
- **Device Discovery**: Automatically discovers all lights on the mesh network
- **Real-time Updates**: Receives status updates from lights via BLE notifications

## Supported Devices

This integration supports Telink BLE Mesh lights sold under various brand names:

- **Fulife** (most common)
- **BTAlliance**
- Other Telink-based mesh lights with compatible firmware

Devices are identified by:
- Local name starting with "Fulife"
- MAC address prefix `FF:00:06:0E` or `FF:05:01:0B`

## Requirements

- Home Assistant 2024.1.0 or newer
- Bluetooth adapter (built-in or USB)
- ESPHome Bluetooth Proxy (recommended for better range)

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → **Custom repositories**
3. Add this repository URL: `https://github.com/YOUR_USERNAME/pyBTAlliance`
4. Select category: **Integration**
5. Click **Add**
6. Search for "BTAlliance Mesh Lights" and click **Download**
7. Restart Home Assistant

> **Note**: You must create a GitHub release (tag) for HACS to detect the integration. After pushing to GitHub, create a release with a version tag like `v1.0.0`.

### Manual Installation

1. Download the `custom_components/btalliance` folder from this repository
2. Copy it to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

### Auto-Discovery

1. Power on your Fulife lights
2. Home Assistant will automatically detect them
3. A notification will appear asking to configure the integration
4. Confirm the default credentials or customize

### Manual Setup

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for "BTAlliance Mesh Lights"
4. Enter mesh credentials:
   - **Mesh Name**: Your mesh network name (default: `Fulife`)
   - **Password**: Your mesh password
5. Select a gateway device from discovered lights
6. All mesh lights will be automatically discovered and added

## How It Works

```
┌─────────────────┐     BLE      ┌─────────────────┐
│  Home Assistant │◄────────────►│  Gateway Light  │
│                 │              │   (any light)   │
└─────────────────┘              └────────┬────────┘
                                          │
                                    Mesh Network
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    │                     │                     │
              ┌─────▼─────┐         ┌─────▼─────┐         ┌─────▼─────┐
              │  Light 1  │         │  Light 2  │         │  Light N  │
              └───────────┘         └───────────┘         └───────────┘
```

1. **Gateway Selection**: The integration connects to one light as the "gateway"
2. **Mesh Discovery**: A broadcast command triggers all lights to report their status
3. **Individual Control**: Commands are addressed to specific mesh addresses
4. **Mesh Forwarding**: Lights forward commands to reach devices out of direct BLE range

## Mesh Addresses

Each light on the mesh has a unique address (1-254). The integration automatically discovers these addresses during setup. You can also use:

- **Broadcast (0xFFFF)**: Control all lights simultaneously
- **Individual**: Control specific lights by their mesh address

## Troubleshooting

### Lights Not Discovered

1. Ensure lights are powered on and in pairing mode
2. Check that your Bluetooth adapter is working
3. Try moving closer to the lights
4. Restart the integration

### Connection Issues

1. Power cycle the ESP32 proxy (if using ESPHome)
2. Ensure no other apps are connected to the lights
3. Check Home Assistant logs for error messages

### Wrong Credentials

If you changed your mesh name or password:
1. Go to the integration options
2. Update the credentials
3. Reload the integration

## Development

### Project Structure

```
custom_components/btalliance/
├── __init__.py          # Integration setup
├── config_flow.py       # Configuration UI
├── const.py             # Constants and defaults
├── coordinator.py       # Mesh network coordinator
├── crypto.py            # Telink encryption
├── light.py             # Light entity
├── manifest.json        # Integration metadata
├── protocol.py          # Packet construction
├── strings.json         # UI strings
└── translations/
    └── en.json          # English translations
```

### Testing Without Home Assistant

The repository includes standalone test scripts:

```bash
# Test basic connectivity
python testharness.py

# Test mesh functionality
python mesh_test.py
```

### Protocol Documentation

The integration implements the Telink BLE Mesh protocol:

- **Service UUID**: `00010203-0405-0607-0809-0a0b0c0d1910`
- **Authentication**: AES-128 encrypted session key exchange
- **Commands**: Encrypted with session key + sequence number
- **Notifications**: Status updates via 0xDB (query response) and 0xDC (mesh broadcast)

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Telink Semiconductor for the BLE Mesh protocol documentation
- Home Assistant community for integration examples
- ESPHome project for Bluetooth proxy support

## Disclaimer

This is an unofficial integration. BTAlliance/Fulife are trademarks of their respective owners. This project is not affiliated with or endorsed by the device manufacturers.
