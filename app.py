import json
import os
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from flask import Flask, jsonify, render_template, request

import db

# ---------------------------------------------------------------------------
# Defaults (overridden by DB settings, which override env vars)
# ---------------------------------------------------------------------------
_DEFAULTS = {
    "mqtt_host":     os.getenv("MQTT_HOST", "localhost"),
    "mqtt_port":     os.getenv("MQTT_PORT", "1883"),
    "mqtt_user":     os.getenv("MQTT_USER", ""),
    "mqtt_pass":     os.getenv("MQTT_PASS", ""),
    "topic_prefix":  os.getenv("TOPIC_PREFIX", "gw"),
}
STALE_SECONDS = int(os.getenv("STALE_SECONDS", "30"))


def get_cfg():
    """Return current MQTT config, merging DB values over defaults."""
    cfg = dict(_DEFAULTS)
    cfg.update(db.all_settings())
    cfg["mqtt_port"] = int(cfg["mqtt_port"])
    return cfg


# ---------------------------------------------------------------------------
# In-memory state
# readings[gateway_mac][tag_mac] = {rssi, last_seen, type, battery}
# ---------------------------------------------------------------------------
readings: dict = {}
seen_gateways: set = set()
seen_tags: set = set()
state_lock = threading.Lock()

mqtt_client = None
mqtt_lock = threading.Lock()

# ---------------------------------------------------------------------------
# MQTT
# ---------------------------------------------------------------------------

def _make_on_connect(topic_prefix):
    def on_connect(client, userdata, flags, reason_code, properties=None):
        topic = f"{topic_prefix}/+/status"
        client.subscribe(topic)
        client.subscribe(f"/{topic}")
        print(f"[MQTT] Connected, subscribed to {topic} and /{topic}")
    return on_connect


def on_message(client, userdata, msg):
    try:
        parts = msg.topic.strip("/").split("/")
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


def start_mqtt(cfg=None):
    global mqtt_client
    if cfg is None:
        cfg = get_cfg()

    with mqtt_lock:
        if mqtt_client is not None:
            try:
                mqtt_client.loop_stop()
                mqtt_client.disconnect()
            except Exception:
                pass

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if cfg["mqtt_user"]:
            client.username_pw_set(cfg["mqtt_user"], cfg["mqtt_pass"])
        client.on_connect = _make_on_connect(cfg["topic_prefix"])
        client.on_message = on_message
        client.connect_async(cfg["mqtt_host"], cfg["mqtt_port"])
        client.loop_start()
        mqtt_client = client
        print(f"[MQTT] Connecting to {cfg['mqtt_host']}:{cfg['mqtt_port']} "
              f"topic={cfg['topic_prefix']}/+/status")


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)


def _format_mac(mac: str) -> str:
    mac = mac.upper().replace(":", "")
    return ":".join(mac[i:i+2] for i in range(0, 12, 2)) if len(mac) == 12 else mac


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    cfg = get_cfg()
    # Never send password back in plaintext; send a placeholder if set
    return jsonify(
        mqtt_host=cfg["mqtt_host"],
        mqtt_port=cfg["mqtt_port"],
        mqtt_user=cfg["mqtt_user"],
        mqtt_pass_set=bool(cfg["mqtt_pass"]),
        topic_prefix=cfg["topic_prefix"],
    )


@app.route("/api/settings", methods=["POST"])
def api_set_settings():
    data = request.json or {}
    fields = ["mqtt_host", "mqtt_port", "mqtt_user", "mqtt_pass", "topic_prefix"]
    for field in fields:
        if field in data and str(data[field]).strip():
            db.set_setting(field, str(data[field]).strip())
    # Reconnect with new settings
    start_mqtt()
    return jsonify(ok=True)


@app.route("/api/data")
def api_data():
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
            try:
                ls = datetime.fromisoformat(info["last_seen"])
                if now_ts - ls.timestamp() > STALE_SECONDS:
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
