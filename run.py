"""Start the research server: python CRAWLER/run.py"""
from pathlib import Path
import argparse
import os
import signal

ROOT = Path(__file__).resolve().parent


def load_environment():
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if key.replace("_", "").isalnum() and key[0].isalpha():
                os.environ.setdefault(key, value.strip('"\''))


def main():
    load_environment()
    parser = argparse.ArgumentParser(description="Trend Crawler research services")
    parser.add_argument("--host", default=os.getenv("CRAWLER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("CRAWLER_PORT", "8765")))
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument("--no-workers", action="store_true", help="Serve saved data without starting collection")
    parser.add_argument("--no-default-sources", action="store_true", help="Use only already configured sources")
    parser.add_argument("--open-browser", action="store_true", help="Open the application on the Python server's address")
    args = parser.parse_args()
    from server.service import ResearchService
    from server.http import AppServer
    service = ResearchService(args.data_dir, seed=not args.no_default_sources)
    try:
        server = AppServer((args.host, args.port), service, ROOT)
    except Exception:
        service.close()
        raise
    public_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
    url = "http://" + public_host + ":" + str(server.server_port) + "/CRAWLER/"
    print("Trend Crawler: " + url, flush=True)
    print("Research database: " + ("PostgreSQL" if service.db.postgres else "SQLite") + "; AI " + ("configured" if service.ai.ready else "not configured"), flush=True)
    print("Open this address for search and OpenAI setup; a separate IDE/static server has no research API.", flush=True)
    if not args.no_workers:
        service.start(int(os.getenv("CRAWLER_WORKERS", "2")))
    def stop_from_signal(signum, _frame):
        # shutdown() must run off the serving thread, including for SIGTERM.
        print("Trend Crawler: shutdown requested (signal " + str(signum) + ")", flush=True)
        server.initiate_shutdown()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop_from_signal)

    if args.open_browser:
        import threading
        import webbrowser
        opener = threading.Timer(.5, lambda: webbrowser.open(url))
        opener.daemon = True
        opener.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.initiate_shutdown()
    finally:
        print("Trend Crawler: stopping research workers and closing HTTP server...", flush=True)
        server.stopping.set()
        service.stop_event.set()
        server.server_close()
        grace = max(1, min(60, int(os.getenv("CRAWLER_SHUTDOWN_GRACE_SECONDS", "15"))))
        active = service.close(grace_period=grace)
        if active:
            print("Trend Crawler: " + ", ".join(active) + " did not finish before shutdown; durable jobs will be recovered after their leases expire.", flush=True)
        print("Trend Crawler: stopped. Research collection is offline.", flush=True)


if __name__ == "__main__":
    main()
