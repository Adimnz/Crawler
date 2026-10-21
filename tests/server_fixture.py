"""Isolated server for the browser integration test; never used by the application."""
from pathlib import Path
import json
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.service import ResearchService
from server.http import AppServer
from server.storage import now_ms

temporary = tempfile.TemporaryDirectory()
service = ResearchService(temporary.name, seed=False, dsn='')
source = service.add_source({'id': 'fixture-office', 'name': 'Fixture Primary Office', 'url': 'https://fixture.example/feed', 'kind': 'rss', 'tier': 'primary', 'language': 'en', 'region': 'North America', 'family': 'Fixture Office', 'permissions': 'Isolated fixture data', 'enabled': False})
other = service.add_source({'id': 'fixture-reporter', 'name': 'Fixture Independent Reporter', 'url': 'https://reporter.example/feed', 'kind': 'rss', 'tier': 'major', 'language': 'en', 'family': 'Fixture Reporter', 'permissions': 'Isolated fixture data', 'enabled': False})
at = now_ms() - 100000
one = service.ingest(source, {'title': 'NVIDIA semiconductor export proposal raises supply chain compliance requirements for manufacturers', 'text': 'NVIDIA semiconductor export proposal raises supply chain compliance requirements for manufacturers. The official proposal estimates annual compliance costs of 12 million dollars.', 'url': 'https://fixture.example/one', 'publishedAt': at})
service.ingest(other, {'title': 'NVIDIA semiconductor export proposal raises supply chain compliance requirements amid regional review', 'text': 'NVIDIA semiconductor export proposal raises supply chain compliance requirements amid regional review. The official proposal estimates annual compliance costs of 27 million dollars.', 'url': 'https://reporter.example/two', 'publishedAt': at + 1000})
service.ingest(source, {'title': 'Central bank publishes an employment and inflation review', 'text': 'The central bank publishes an employment and inflation review. This fixture is not a live economic report.', 'url': 'https://fixture.example/three', 'publishedAt': at + 2000})
for event in service.db.list('event'):
    service.analyze_event(event['id'])
server = AppServer(('127.0.0.1', 0), service, Path(__file__).resolve().parents[1], auth_token='')
print(json.dumps({'port': server.server_port, 'documentId': one['id'], 'eventId': one['eventId']}), flush=True)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
    service.close()
    temporary.cleanup()
