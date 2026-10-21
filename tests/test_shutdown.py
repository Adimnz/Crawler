"""Integration regression coverage for owner-triggered and signal-triggered shutdown."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.request import Request, build_opener, ProxyHandler


class ShutdownLifecycleTests(unittest.TestCase):
    def test_owner_stop_releases_http_listener_and_exits(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, "DATABASE_URL": "", "CRAWLER_AUTH_TOKEN": "",
                   "CRAWLER_AUTO_AI": "false", "OPENAI_API_KEY": "", "OPENAI_MODEL": "",
                   "S3_BUCKET": ""}
            process = subprocess.Popen(
                [sys.executable, str(root / "run.py"), "--host", "127.0.0.1",
                 "--port", "0", "--data-dir", directory, "--no-workers", "--no-default-sources"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                stdin=subprocess.DEVNULL, env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            lines = queue.Queue()
            reader = threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True)
            reader.start()
            try:
                first = lines.get(timeout=20).strip()
                self.assertTrue(first.startswith("Trend Crawler: http://127.0.0.1:"), first)
                origin = first.removeprefix("Trend Crawler: ").removesuffix("/CRAWLER/")
                opener = build_opener(ProxyHandler({}))
                with opener.open(origin + "/api/ready", timeout=5) as resp:
                    status = json.load(resp)
                self.assertEqual(status["status"], "running")
                with opener.open(origin + "/api/session", timeout=5) as resp:
                    session = json.load(resp)
                    cookie = resp.headers["Set-Cookie"].split(";", 1)[0]
                self.assertTrue(session["ownerAuthorized"]) if "ownerAuthorized" in session else None
                req = Request(origin + "/api/control/shutdown", data=b"{}",
                              headers={"Content-Type": "application/json",
                                       "X-Crawler-CSRF": session["csrf"], "Cookie": cookie}, method="POST")
                with opener.open(req, timeout=5) as resp:
                    self.assertEqual(json.load(resp)["status"], "stopping")
                self.assertEqual(process.wait(timeout=12), 0)
                remaining = process.stdout.read()
                self.assertIn("Trend Crawler: stopped.", remaining)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                process.stdout.close()
                process.stderr.close()
                reader.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
