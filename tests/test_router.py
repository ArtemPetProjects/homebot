# PURPOSE: тесты чтения устройств роутера с подменённым HTTP.
import json
import unittest
from types import SimpleNamespace

from homebot.config import Config
from homebot.infrastructure.router import RouterClient
from homebot.infrastructure.router_crypto import KEY, aes_cbc_encrypt


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def response(payload):
    return FakeResponse(payload)


class RouterTest(unittest.TestCase):
    def test_login_and_devices(self):
        login_data = {"cookie": "abc", "loginStatus": "success"}
        hosts = {
            "lanHostList": [
                {
                    "lanHostOnlineHostName": "Android-TV",
                    "lanHostIpv4Address": "192.168.1.2",
                    "lanHostMac": "78:53:33:4a:40:64",
                    "lanHostOnlineState": True,
                    "lanHostOnlineTime": "100",
                },
                {
                    "lanHostOnlineHostName": "N/A",
                    "lanHostIpv4Address": "",
                    "lanHostMac": "60:3D:61:65:49:4A",
                    "lanHostOnlineState": False,
                    "lanHostOnlineTime": "40",
                },
            ]
        }
        replies = [
            response({"result": True, "parameter": aes_cbc_encrypt(json.dumps(login_data), KEY, KEY)}),
            response({"result": True, "parameter": aes_cbc_encrypt(json.dumps(hosts), KEY, KEY)}),
        ]
        config = Config(
            bot_token="t", chat_id=1, api_key="k", host="127.0.0.1", port=1,
            send_enabled=False, poll_interval=1, ask_ttl_minutes=30,
            router_url="http://192.168.1.1", router_login="admin", router_password="pw",
        )
        client = RouterClient(config, opener=lambda request, timeout: replies.pop(0))
        devices = client.devices()
        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0].name, "Android TV")
        self.assertTrue(devices[0].online)
        self.assertEqual(devices[1].name, "")
        self.assertFalse(devices[1].online)


if __name__ == "__main__":
    unittest.main()
