"""Isolated public-network connectors. Credentials are read from server environment only."""
from __future__ import annotations

import base64
import datetime as dt
import email.utils
import hashlib
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import threading
import time
from urllib.parse import urljoin, urlsplit, urlencode, parse_qsl, urlunsplit
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET


USER_AGENT = "TrendCrawler/2.0 (+local research; feed and document collection)"


class ConnectorError(Exception):
    def __init__(self, message, retry_after=None, status=None):
        super().__init__(message)
        self.retry_after = retry_after
        self.status = status


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skipping = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.skipping += 1
        if tag in {"p", "div", "br", "h1", "h2", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.skipping = max(0, self.skipping - 1)

    def handle_data(self, text):
        if not self.skipping:
            self.parts.append(text)


def strip_html(text):
    parser = TextExtractor()
    parser.feed(str(text))
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def timestamp(value, fallback=None):
    if isinstance(value, (float, int)):
        return int(value * 1000 if value < 100000000000 else value)
    if value:
        try:
            parsed = email.utils.parsedate_to_datetime(value)
        except (ValueError, TypeError):
            try:
                parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return fallback
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return int(parsed.timestamp() * 1000)
    return fallback


def validate_public_url(url, resolver=socket.getaddrinfo):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ConnectorError("Sources must use public HTTPS URLs without embedded credentials")
    if parsed.port not in (None, 443):
        raise ConnectorError("Only HTTPS port 443 is allowed for source collection")
    try:
        addresses = list(dict.fromkeys(item[4][0] for item in resolver(parsed.hostname, 443, type=socket.SOCK_STREAM)))
    except OSError as exc:
        raise ConnectorError("Source hostname could not be resolved") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ConnectorError("Private, loopback, link-local, and reserved source addresses are blocked")
    return parsed, sorted(addresses, key=lambda address: ":" in address)


class Network:
    def __init__(self):
        self.lock, self.host_due, self.robots_cache = threading.Lock(), {}, {}

    def fetch(self, url, headers=None, limit=6 * 1024 * 1024, method="GET", body=None):
        original_host = urlsplit(url).hostname
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity", **(headers or {})}
        for _ in range(5):
            parsed, addresses = validate_public_url(url)
            with self.lock:
                now = time.monotonic()
                if len(self.host_due) > 2048:
                    self.host_due = {host: due for host, due in self.host_due.items() if due > now}
                    if len(self.host_due) > 2048:
                        self.host_due.clear()
                delay = max(0, self.host_due.get(parsed.hostname, 0) - now)
                self.host_due[parsed.hostname] = now + delay + .5
            if delay:
                time.sleep(min(delay, 5))
            connection = http.client.HTTPSConnection(parsed.hostname, timeout=90 if parsed.hostname == "api.openai.com" else 20, context=ssl.create_default_context())
            # Pin the validated address while preserving the original TLS hostname/SNI.
            approved = addresses[0]
            connection._create_connection = lambda address, timeout=20, source_address=None, **kw: socket.create_connection((approved, address[1]), timeout, source_address)
            scoped_headers = headers if parsed.hostname == original_host else {k: v for k, v in headers.items() if k.lower() in {"user-agent", "accept", "accept-encoding", "content-type"}}
            try:
                target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
                connection.request(method, target, body=body, headers=scoped_headers)
                response = connection.getresponse()
                metadata = {k.lower(): v for k, v in response.getheaders()}
                if response.status in {301, 302, 303, 307, 308}:
                    location = metadata.get("location")
                    if not location:
                        raise ConnectorError("Source redirect has no destination")
                    url = urljoin(url, location)
                    if response.status == 303:
                        method, body = "GET", None
                    continue
                if response.status >= 400:
                    retry = metadata.get("retry-after", "")
                    delay_seconds = int(retry) if retry.isdigit() else max(0, ((timestamp(retry) or 0) / 1000) - time.time())
                    raise ConnectorError("Provider returned HTTP " + str(response.status), min(3600, delay_seconds) or None, status=response.status)
                if int(metadata.get("content-length", "0") or 0) > limit:
                    raise ConnectorError("Source record exceeds the collection size limit")
                data = response.read(limit + 1)
                if len(data) > limit:
                    raise ConnectorError("Source record exceeds the collection size limit")
                return data, metadata, url
            except (OSError, http.client.HTTPException) as exc:
                raise ConnectorError("Source connection failed or timed out") from exc
            finally:
                connection.close()
        raise ConnectorError("Source redirected too many times")

    def allowed(self, url):
        parsed, _ = validate_public_url(url)
        origin = "https://" + parsed.hostname
        cached = self.robots_cache.get(origin)
        if not cached or cached[0] < time.time() - 3600:
            parser = RobotFileParser(origin + "/robots.txt")
            try:
                data, _, _ = self.fetch(origin + "/robots.txt", limit=512000)
                parser.parse(data.decode("utf-8", "replace").splitlines())
            except ConnectorError as exc:
                if "HTTP 404" in str(exc) or "HTTP 410" in str(exc):
                    parser.parse([])
                else:
                    raise ConnectorError("Cannot establish robots.txt collection permission") from exc
            with self.lock:
                if len(self.robots_cache) >= 512:
                    expired = [host for host, item in self.robots_cache.items() if item[0] < time.time() - 3600]
                    for host in expired:
                        self.robots_cache.pop(host, None)
                    if len(self.robots_cache) >= 512:
                        self.robots_cache.pop(next(iter(self.robots_cache)))
                self.robots_cache[origin] = (time.time(), parser)
        return self.robots_cache[origin][1].can_fetch(USER_AGENT, url)

    def json(self, url, headers=None, body=None):
        data, _, _ = self.fetch(url, headers=headers, method="POST" if body is not None else "GET", body=json.dumps(body).encode() if body is not None else None)
        return json.loads(data)


def feed_records(data, source):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ConnectorError("XML declarations containing entities or document types are not accepted")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ConnectorError("Source did not return valid RSS/Atom XML") from exc
    local = lambda tag: tag.rsplit("}", 1)[-1]
    results = []
    for item in root.iter():
        if local(item.tag) not in {"item", "entry"}:
            continue
        fields, authors = {}, []
        for child in item:
            name = local(child.tag)
            if name in {"author", "creator"}:
                names = ["".join(element.itertext()) for element in child if local(element.tag) == "name"]
                credited = names or [child.text or ""]
                authors.extend(strip_html(value).strip() for value in credited if strip_html(value).strip())
            if name == "link" and child.attrib.get("rel", "alternate") == "alternate":
                fields["url"] = child.attrib.get("href") or child.text or ""
            else:
                fields[name] = "".join(child.itertext())
        title = strip_html(fields.get("title", ""))
        url = fields.get("url", "").strip()
        if not title or not url.startswith("https://"):
            continue
        description = fields.get("description") or fields.get("summary") or fields.get("content") or ""
        published = timestamp(fields.get("pubDate") or fields.get("published") or fields.get("updated"))
        results.append({"title": title[:1500], "text": (title + ". " + strip_html(description))[:30000], "url": url, "publishedAt": published,
                        "authors": list(dict.fromkeys(authors))[:8],
                        "publishedEstimated": published is None, "raw": fields, "language": source.get("language", "unknown")})
    return results[:200]


def dotted(value, path, default=None):
    for part in str(path).split("."):
        if not part:
            continue
        if isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        elif isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return default
    return value


def collect(source, network):
    kind = source.get("kind", "rss")
    config = source.get("config", {})
    headers = {}
    credential_env = source.get("credentialEnv", "")
    if credential_env:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,80}", credential_env):
            raise ConnectorError("Invalid credential environment variable name")
        secret = os.getenv(credential_env, "")
        if not secret:
            raise ConnectorError("Required server credential is not configured")
        headers[source.get("credentialHeader", "Authorization")] = source.get("credentialPrefix", "Bearer ") + secret
    if kind == "rss":
        if not network.allowed(source["url"]):
            raise ConnectorError("Feed collection is disallowed by robots.txt")
        data, metadata, resolved = network.fetch(source["url"], headers)
        return {"documents": feed_records(data, source), "raw": data, "metadata": metadata, "resolvedUrl": resolved}
    if kind == "coingecko":
        url = "https://api.coingecko.com/api/v3/simple/price?" + urlencode({"ids": ",".join(config.get("ids", ["bitcoin", "ethereum"])), "vs_currencies": "usd", "include_24hr_vol": "true", "include_24hr_change": "true", "include_last_updated_at": "true"})
        key = os.getenv("COINGECKO_API_KEY")
        payload = network.json(url, {"x-cg-demo-api-key": key} if key else {})
        observations = [{"assetId": "crypto:coingecko:" + asset, "assetClass": "crypto", "metric": "price_usd", "value": item.get("usd"), "observedAt": timestamp(item.get("last_updated_at")), "volume24h": item.get("usd_24h_vol"), "change24h": item.get("usd_24h_change") } for asset, item in payload.items()]
        return {"observations": observations, "raw": json.dumps(payload).encode()}
    if kind == "fred":
        key = os.getenv("FRED_API_KEY")
        if not key:
            raise ConnectorError("FRED_API_KEY is not configured")
        series = str(config.get("series", "CPIAUCSL"))
        payload = network.json("https://api.stlouisfed.org/fred/series/observations?" + urlencode({"series_id": series, "api_key": key, "file_type": "json", "sort_order": "desc", "limit": 100}))
        observations = [{"assetId": "economic:fred:" + series, "assetClass": "economic", "metric": "level", "value": float(row["value"]), "observedAt": timestamp(row["date"]), "revisionDate": row.get("realtime_start")} for row in payload.get("observations", []) if row.get("value") not in {None, "."}]
        return {"observations": observations, "raw": json.dumps(payload).encode()}
    if kind == "json":
        payload = network.json(source["url"], headers)
        rows = dotted(payload, config.get("itemsPath", ""), [])
        if not isinstance(rows, list):
            raise ConnectorError("Configured JSON item path must resolve to an array")
        observations, documents = [], []
        for row in rows[:500]:
            fields = {name: dotted(row, field) for name, field in config.get("fields", {}).items()}
            if config.get("recordType") == "observation":
                # Explicit namespaces prevent stocks, bridged tokens, and chain assets sharing a ticker from merging.
                asset_id = str(fields.get("assetId") or config.get("assetId", ""))
                if ":" not in asset_id:
                    raise ConnectorError("Quantitative connectors require a namespaced assetId, not a bare ticker")
                fields.update(assetId=asset_id, assetClass=config.get("assetClass", "unknown"), metric=config.get("metric", "price_usd"), observedAt=timestamp(fields.get("observedAt")))
                observations.append(fields)
            else:
                documents.append({**fields, "publishedAt": timestamp(fields.get("publishedAt")), "raw": row})
        return {"documents": documents, "observations": observations, "raw": json.dumps(payload).encode()}
    raise ConnectorError("Unsupported connector type")


DEFAULT_SOURCES = [
    {"id": "fed", "name": "Federal Reserve", "url": "https://www.federalreserve.gov/feeds/press_all.xml", "family": "Federal Reserve", "tier": "primary", "language": "en", "region": "North America", "geographyVerified": True, "category": "Economics", "kind": "rss", "enabled": True},
    {"id": "bbc", "name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "family": "BBC", "tier": "major", "language": "en", "region": "Europe", "geographyVerified": True, "category": "Politics", "kind": "rss", "enabled": True},
    {"id": "bbc-mundo", "name": "BBC Mundo", "url": "https://feeds.bbci.co.uk/mundo/rss.xml", "family": "BBC", "tier": "major", "language": "es", "region": "Latin America", "geographyVerified": False, "category": "Politics", "kind": "rss", "enabled": True},
    {"id": "techcrunch", "name": "TechCrunch", "url": "https://techcrunch.com/feed/", "family": "TechCrunch", "tier": "specialist", "language": "en", "region": "North America", "geographyVerified": False, "category": "Technology", "kind": "rss", "enabled": True},
    {"id": "coingecko", "name": "CoinGecko prices", "url": "https://api.coingecko.com/api/v3/simple/price", "family": "CoinGecko", "tier": "specialist", "language": "en", "kind": "coingecko", "enabled": False, "config": {"ids": ["bitcoin", "ethereum"]}},
    {"id": "fred", "name": "FRED inflation", "url": "https://api.stlouisfed.org/fred/series/observations", "family": "Federal Reserve Bank of St. Louis", "tier": "primary", "language": "en", "kind": "fred", "enabled": False, "config": {"series": "CPIAUCSL"}},
]
