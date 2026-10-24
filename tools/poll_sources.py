"""Check public feeds or collect them once, without starting AI/analysis workers."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import argparse
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.connectors import DEFAULT_SOURCES, Network, collect
from server.service import ResearchService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", action="store_true", help="Install catalogue updates and retain usable feed items in the application database")
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument("--source", action="append", help="Limit to this source ID (repeatable)")
    parser.add_argument("--report", help="Write the measured connection report to this JSON path")
    args = parser.parse_args()
    service = ResearchService(args.data_dir) if args.collect else None
    if service: service.auto_ai = False  # This command never schedules paid enrichment.
    network = service.network if service else Network()
    sources = service.db.list("source") if service else DEFAULT_SOURCES
    sources = [s for s in sources if s.get("enabled") and (s["kind"] == "rss" or s["id"] == "hn-api") and (not args.source or s["id"] in args.source)]

    def check(source):
        start = time.monotonic()
        row = {"id": source["id"], "name": source["name"], "url": source["url"], "contentRole": source.get("contentRole", "reporting")}
        try:
            if service:
                health = service.poll_source(source["id"])
                row.update(ok=health["ok"], items=health["totalItems"], status=health["status"], lastPoll=health["lastPoll"])
            else:
                result = collect(source, network)
                row.update(ok=True, items=len(result.get("documents", [])), resolvedUrl=result.get("resolvedUrl"))
        except Exception as exc:
            from server.connectors import ConnectorError
            row.update(ok=False, error=str(exc) if isinstance(exc, (ConnectorError, ValueError)) else "Collection failed: " + type(exc).__name__)
        row["seconds"] = round(time.monotonic() - start, 2)
        return row

    results = []
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            for future in as_completed([pool.submit(check, source) for source in sources]):
                row = future.result()
                results.append(row)
                print(json.dumps(row, ensure_ascii=True), flush=True)
    finally:
        if service: service.close()
    report = {"checkedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "mode": "collected" if service else "checked",
              "checked": len(results), "connected": sum(row["ok"] for row in results), "results": sorted(results, key=lambda r: r["id"])}
    if args.report: Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}))


if __name__ == "__main__":
    main()
