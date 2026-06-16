"""VIDAA OS Hisense TV client via MQTT (port 36669)."""

from __future__ import annotations

import json
import ssl
import threading
import time
import uuid
from typing import Any

import paho.mqtt.client as mqtt

CLIENT_NAME = "HisenseRemote"
MQTT_PORT = 36669
MQTT_USER = "hisenseservice"
MQTT_PASS = "multimqttservice"

KEY_MAP = {
    "power": "KEY_POWER",
    "up": "KEY_UP",
    "down": "KEY_DOWN",
    "left": "KEY_LEFT",
    "right": "KEY_RIGHT",
    "ok": "KEY_OK",
    "back": "KEY_RETURNS",
    "menu": "KEY_MENU",
    "exit": "KEY_EXIT",
    "home": "KEY_HOME",
    "volume_up": "KEY_VOLUMEUP",
    "volume_down": "KEY_VOLUMEDOWN",
    "mute": "KEY_MUTE",
    "channel_up": "KEY_CHANNELUP",
    "channel_down": "KEY_CHANNELDOWN",
    "play": "KEY_PLAY",
    "pause": "KEY_PAUSE",
    "stop": "KEY_STOP",
    "rewind": "KEY_BACK",
    "fast_forward": "KEY_FORWARDS",
    "subtitle": "KEY_SUBTITLE",
    "0": "KEY_0",
    "1": "KEY_1",
    "2": "KEY_2",
    "3": "KEY_3",
    "4": "KEY_4",
    "5": "KEY_5",
    "6": "KEY_6",
    "7": "KEY_7",
    "8": "KEY_8",
    "9": "KEY_9",
}


class VidaaTvClient:
    def __init__(self, host: str, *, use_ssl: bool = True, timeout: float = 5.0):
        self.host = host
        self.use_ssl = use_ssl
        self.timeout = timeout
        self._client_id = f"hisense-remote-{uuid.uuid4().hex[:8]}"
        self._connected = threading.Event()
        self._responses: dict[str, Any] = {}
        self._response_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._client = self._build_client()

    def _build_client(self) -> mqtt.Client:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self._client_id,
            protocol=mqtt.MQTTv311,
        )
        client.username_pw_set(MQTT_USER, MQTT_PASS)
        if self.use_ssl:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            client.tls_set_context(ctx)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        return client

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            client.subscribe("#")
            self._connected.set()

    def _on_message(self, client, userdata, message):
        topic = message.topic
        payload = message.payload.decode("utf-8", errors="replace")
        with self._lock:
            self._responses[topic] = payload
            for prefix, event in list(self._response_events.items()):
                if topic.startswith(prefix) or prefix in topic:
                    event.set()

    def connect(self) -> None:
        self._client.connect(self.host, MQTT_PORT, keepalive=60)
        self._client.loop_start()
        if not self._connected.wait(self.timeout):
            raise ConnectionError(f"Could not connect to VIDAA TV at {self.host}:{MQTT_PORT}")

    def disconnect(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
        self._connected.clear()

    def _publish(self, topic: str, payload: str | int = "") -> None:
        self._client.publish(topic, payload if payload != "" else "0", qos=0)

    def _wait_for_topic(self, topic_prefix: str) -> str | None:
        event = threading.Event()
        with self._lock:
            self._response_events[topic_prefix] = event
        if event.wait(self.timeout):
            with self._lock:
                for topic, payload in self._responses.items():
                    if topic_prefix in topic:
                        return payload
        return None

    def start_authorization(self) -> None:
        """Trigger the 4-digit PIN on the TV screen."""
        topic = f"/remoteapp/tv/ui_service/{CLIENT_NAME}/actions/startauthentication"
        self._publish(topic, "")

    def send_auth_code(self, code: str | int) -> None:
        topic = f"/remoteapp/tv/ui_service/{CLIENT_NAME}/actions/authenticationcode"
        self._publish(topic, json.dumps({"authNum": int(code)}))

    def send_key(self, key: str) -> None:
        mqtt_key = KEY_MAP.get(key, key if key.startswith("KEY_") else f"KEY_{key.upper()}")
        topic = f"/remoteapp/tv/remote_service/{CLIENT_NAME}/actions/sendkey"
        self._publish(topic, mqtt_key)

    def get_volume(self) -> dict[str, Any] | None:
        topic = f"/remoteapp/tv/platform_service/{CLIENT_NAME}/actions/getvolume"
        response_topic = "/remoteapp/mobile/broadcast/ui_service/volume"
        with self._lock:
            self._responses.pop(response_topic, None)
        self._publish(topic, "")
        payload = self._wait_for_topic(response_topic)
        if payload:
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                return {"raw": payload}
        return None

    def set_volume(self, level: int) -> None:
        if not 0 <= level <= 100:
            raise ValueError("Volume must be between 0 and 100")
        topic = f"/remoteapp/tv/platform_service/{CLIENT_NAME}/actions/changevolume"
        self._publish(topic, str(level))

    def get_sources(self) -> list[dict[str, Any]]:
        topic = f"/remoteapp/tv/ui_service/{CLIENT_NAME}/actions/sourcelist"
        response_topic = f"/remoteapp/mobile/{CLIENT_NAME}/ui_service/data/sourcelist"
        with self._lock:
            self._responses.pop(response_topic, None)
        self._publish(topic, "0")
        payload = self._wait_for_topic(response_topic)
        if payload:
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                return []
        return []

    def set_source(self, source_id: str, source_name: str = "") -> None:
        topic = f"/remoteapp/tv/ui_service/{CLIENT_NAME}/actions/changesource"
        data: dict[str, str] = {"sourceid": str(source_id)}
        if source_name:
            data["sourcename"] = source_name.replace(" ", "")
        self._publish(topic, json.dumps(data))

    def launch_app(self, name: str, url: str) -> None:
        topic = f"/remoteapp/tv/ui_service/{CLIENT_NAME}/actions/launchapp"
        payload = {
            "name": name,
            "urlType": 37,
            "storeType": 0,
            "url": url,
        }
        self._publish(topic, json.dumps(payload))

    def get_tv_state(self) -> dict[str, Any] | None:
        topic = f"/remoteapp/tv/ui_service/{CLIENT_NAME}/actions/gettvstate"
        response_topic = "/remoteapp/mobile/broadcast/ui_service/state"
        with self._lock:
            self._responses.pop(response_topic, None)
        self._publish(topic, "0")
        payload = self._wait_for_topic(response_topic)
        if payload:
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                return {"raw": payload}
        return None


def probe_vidaa(host: str, *, use_ssl: bool = True, timeout: float = 3.0) -> bool:
    client = VidaaTvClient(host, use_ssl=use_ssl, timeout=timeout)
    try:
        client.connect()
        return True
    except Exception:
        return False
    finally:
        try:
            client.disconnect()
        except Exception:
            pass