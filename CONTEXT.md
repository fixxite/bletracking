# Project Context — BLE Indoor Tracking

## What this is
Indoor BLE tracking system using Minew G1 gateways over MQTT.
A Flask web app subscribes to MQTT tag readings, maintains live proximity data, and serves a dashboard.

## Current state
- Fully working as of 2026-03-24
- Real Minew G1 gateway (192.168.20.84) confirmed publishing on `/gw/gw1/status`
- 23 tags detected live from gateway GW1
- Fixed MQTT topic leading-slash issue; app now subscribes to both `gw/+/status` and `/gw/+/status`
- mosquitto (apt) configured to listen on `0.0.0.0:1883`

## File map
| File | Role |
|---|---|
| `app.py` | Flask server + MQTT background thread + REST API |
| `db.py` | SQLite helpers — persists gateway/tag display names |
| `requirements.txt` | `flask`, `paho-mqtt` |
| `templates/index.html` | Live dashboard (auto-refresh every 3s) + naming UI |
| `ble_tracker.db` | Auto-created at runtime; stores names |

## MQTT protocol (Minew G1)
- **Subscribe topic**: `{TOPIC_PREFIX}/+/status` — gateway MAC is the middle segment
- **Payload**: JSON array of tag detections
  ```json
  [{"mac":"AC233FA2495C","rssi":-55,"type":"S1","timestamp":"...","battery":100}]
  ```
- Closest gateway = highest RSSI for a tag across all gateways

## Configuration (env vars)
| Variable | Default | Purpose |
|---|---|---|
| `MQTT_HOST` | `localhost` | Broker hostname |
| `MQTT_PORT` | `1883` | Broker port |
| `MQTT_USER` | `` | Auth username |
| `MQTT_PASS` | `` | Auth password |
| `TOPIC_PREFIX` | `gw` | MQTT topic prefix |
| `STALE_SECONDS` | `30` | Drop readings older than this |

## API endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Dashboard HTML |
| GET | `/api/data` | Live JSON — gateways + tags + names |
| POST | `/api/gateway/<mac>/name` | Set gateway display name |
| POST | `/api/tag/<mac>/name` | Set tag display name |

## How to run
```bash
MQTT_HOST=your-broker python3 app.py
# → http://localhost:5000
```

## Test with simulated gateway
```bash
mosquitto_pub -t "/gw/gw1/status" \
  -m '[{"mac":"AA:BB:CC:DD:EE:FF","rssi":-55,"type":"S1","timestamp":"2026-03-24T10:00:00Z"}]'
```

## Real hardware
- Gateway: Minew G1 at 192.168.20.84
- Broker: 192.168.20.196:1883 (this machine, mosquitto via apt)
- Topic: `/gw/gw1/status`

## Known limitations / future work
- No historical data storage (readings are in-memory only)
- No authentication on the web interface
- Single MQTT broker supported per instance

## Session log
### 2026-03-24
- Created project from scratch
- Implemented MQTT subscriber, Flask API, SQLite name persistence, live dashboard
- Started app (PID 4027881, port 5000), verified with mosquitto_pub
- Confirmed: 2 gateways, 3 tags, RSSI sorting, stale filtering all working
- CLAUDE.md and CONTEXT.md added for session continuity
- Fixed mosquitto to listen on 0.0.0.0:1883 (was localhost only)
- Fixed MQTT topic leading-slash mismatch (`/gw/gw1/status`)
- Real gateway (192.168.20.84) connected; 23 live tags visible on dashboard
