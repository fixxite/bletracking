import json
import os
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from flask import Flask, jsonify, render_template, request

import db

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MQTT_HOST     = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT     = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER     = os.getenv("MQTT_USER", "")
MQTT_PASS     = os.getenv("MQTT_PASS", "")
TOPIC_PREFIX  = os.getenv("TOPIC_PREFIX", "gw")   # subscribes to <prefix>/+/status
STALE_SECONDS = int(os.getenv("STALE_SECONDS", "30"))

# ---------------------------------------------------------------------------
# In-memory state
# readings[gateway_mac][tag_mac] = {rssi, last_seen, type, battery}
# ---------------------------------------------------------------------------
readings: dict = {}
seen_gateways: set = set()
seen_tags: set = set()
state_lock = threading.Lock()

# ---------------------------------------------------------------------------
# MQTT callbacks
# ---------------------------------------------------------------------------

def on_connect(client, userdata, flags, reason_code, properties=None):
    # Subscribe both with and without leading slash
    topic = f"{TOPIC_PREFIX}/+/status"
    client.subscribe(topic)
    client.subscribe(f"/{topic}")
    print(f"[MQTT] Connected, subscribed to {topic} and /{topic}")


def on_message(client, userdata, msg):
    try:
        parts = msg.topic.strip("/").split("/")
        # Expect <prefix>/<gateway_mac>/status
        if len(parts) < 2:
            return
        gateway_mac = parts[-2].upper()

        payload = json.loads(msg.payload.decode())
        if not isinstance(payload, list):
            payload = [payload]

        now = datetime.now(timezone.utc).isoformat()

        with state_lock:
            seen_gateways.add(gateway_mac)
            if gateway_mac not in readings:
                readings[gateway_mac] = {}

            for item in payload:
                tag_mac = item.get("mac", "").upper().replace(":", "")
                if not tag_mac:
                    continue
                rssi = item.get("rssi")
                if rssi is None:
                    continue
                seen_tags.add(tag_mac)
                readings[gateway_mac][tag_mac] = {
                    "rssi":      rssi,
                    "last_seen": now,
                    "type":      item.get("type", ""),
                    "battery":   item.get("battery"),
                }
    except Exception as exc:
        print(f"[MQTT] Error processing message: {exc}")


def start_mqtt():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(MQTT_HOST, MQTT_PORT)
    client.loop_start()
    return client


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)


def _format_mac(mac: str) -> str:
    """Format a 12-char MAC string as XX:XX:XX:XX:XX:XX."""
    mac = mac.upper().replace(":", "")
    return ":".join(mac[i:i+2] for i in range(0, 12, 2)) if len(mac) == 12 else mac


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def api_data():
    cutoff = time.time() - STALE_SECONDS
    now_ts = time.time()

    with state_lock:
        gw_snapshot = {gw: dict(tags) for gw, tags in readings.items()}
        gw_seen = set(seen_gateways)
        tag_seen = set(seen_tags)

    gw_names  = db.all_names("gateway_names")
    tag_names = db.all_names("tag_names")

    gateways_out = []
    for gw_mac in sorted(gw_seen):
        tags_raw = gw_snapshot.get(gw_mac, {})
        tags_out = []
        for tag_mac, info in tags_raw.items():
            # Filter stale
            try:
                ls = datetime.fromisoformat(info["last_seen"])
                age = now_ts - ls.timestamp()
                if age > STALE_SECONDS:
                    continue
            except Exception:
                pass

            tags_out.append({
                "mac":       _format_mac(tag_mac),
                "mac_raw":   tag_mac,
                "name":      tag_names.get(tag_mac, ""),
                "rssi":      info["rssi"],
                "last_seen": info["last_seen"],
                "type":      info["type"],
                "battery":   info["battery"],
            })

        tags_out.sort(key=lambda t: t["rssi"], reverse=True)

        gateways_out.append({
            "mac":     _format_mac(gw_mac),
            "mac_raw": gw_mac,
            "name":    gw_names.get(gw_mac, ""),
            "tags":    tags_out,
        })

    all_gateways = [
        {"mac": _format_mac(m), "mac_raw": m, "name": gw_names.get(m, "")}
        for m in sorted(gw_seen)
    ]
    all_tags = [
        {"mac": _format_mac(m), "mac_raw": m, "name": tag_names.get(m, "")}
        for m in sorted(tag_seen)
    ]

    return jsonify(gateways=gateways_out, all_gateways=all_gateways, all_tags=all_tags)


@app.route("/api/gateway/<mac>/name", methods=["POST"])
def set_gateway_name(mac):
    name = (request.json or {}).get("name", "").strip()
    if not name:
        return jsonify(error="name required"), 400
    db.set_name("gateway_names", mac, name)
    return jsonify(ok=True)


@app.route("/api/tag/<mac>/name", methods=["POST"])
def set_tag_name(mac):
    name = (request.json or {}).get("name", "").strip()
    if not name:
        return jsonify(error="name required"), 400
    db.set_name("tag_names", mac, name)
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    db.init_db()
    start_mqtt()
    app.run(host="0.0.0.0", port=5000, debug=False)
