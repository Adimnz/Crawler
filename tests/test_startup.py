"""Exercise the real Python entry point without providers or production data."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request


class StartupTests(unittest.TestCase):
    def test_printed_python_url_serves_ready_api_and_search_interface(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            environment = {**os.environ, "OPENAI_API_KEY": "", "OPENAI_MODEL": "", "CRAWLER_AUTO_AI": "false", "DATABASE_URL": "", "S3_BUCKET": ""}
            process = subprocess.Popen([sys.executable, str(root / "run.py"), "--host", "127.0.0.1", "--port", "0", "--data-dir", directory, "--no-workers", "--no-default-sources"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True, env=environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            line = queue.Queue()
            reader = threading.Thread(target=lambda: line.put(process.stdout.readline()), daemon=True)
            reader.start()
            try:
                first = line.get(timeout=20).strip()
                self.assertTrue(first.startswith("Trend Crawler: http://127.0.0.1:"), first)
                url = first.removeprefix("Trend Crawler: ")
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(url.replace("/CRAWLER/", "/api/ready"), timeout=5) as response:
                    ready = json.load(response)
                self.assertEqual(ready["service"], "trend-crawler")
                self.assertTrue(ready["ready"])
                with opener.open(url, timeout=5) as response:
                    html = response.read().decode()
                self.assertIn('id="start-heading">Where do I start', html)
                self.assertIn('<select name="model"', html)
            finally:
                process.terminate()
                process.wait(timeout=5)
                process.stdout.close()
                process.stderr.close()
                reader.join(timeout=1)


if __name__ == "__main__": unittest.main()
