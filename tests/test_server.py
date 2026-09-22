import unittest
import json
import threading
import time
import urllib.request
import urllib.error
from app.server import run_server


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = 8799
        cls.server_thread = threading.Thread(
            target=run_server,
            kwargs={"port": cls.port, "open_browser": False},
            daemon=True
        )
        cls.server_thread.start()
        time.sleep(1.0)

    def test_status_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/status"
        res = urllib.request.urlopen(url)
        self.assertEqual(res.status, 200)
        data = json.loads(res.read().decode("utf-8"))
        self.assertEqual(data.get("status"), "ONLINE")
        self.assertEqual(data.get("agent"), "AUREX")

    def test_command_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/command"
        payload = json.dumps({"command": "What is your name?"}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        res = urllib.request.urlopen(req)
        self.assertEqual(res.status, 200)
        data = json.loads(res.read().decode("utf-8"))
        self.assertTrue(data.get("success"))
        self.assertIn("AUREX", data.get("response"))

    def test_static_ui_served(self):
        url = f"http://127.0.0.1:{self.port}/"
        res = urllib.request.urlopen(url)
        self.assertEqual(res.status, 200)
        content = res.read().decode("utf-8")
        self.assertIn("root", content)

    def test_cors_headers_present(self):
        url = f"http://127.0.0.1:{self.port}/api/status"
        req = urllib.request.Request(url, method="OPTIONS")
        res = urllib.request.urlopen(req)
        self.assertEqual(res.headers.get("Access-Control-Allow-Origin"), "*")


if __name__ == "__main__":
    unittest.main()
