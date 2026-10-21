from pathlib import Path
import json
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.service import ResearchService
from server.http import AppServer
from test_source_collection import Network

tmp = tempfile.TemporaryDirectory()
service = ResearchService(tmp.name, Network(), seed=False, dsn='')
for i in range(22):
    service.add_source({'id':'source-'+str(i),'name':'Publisher '+str(i),'kind':'rss','url':'https://publisher.example/feed/'+str(i),
                        'contentRole':'discovery' if i==1 else 'reporting','enabled':i<3})
service.poll_source('source-0')
service.poll_source('source-1')
service.network.denied='https://publisher.example/feed/2'
try: service.poll_source('source-2')
except Exception: pass
server=AppServer(('127.0.0.1',0), service, Path(__file__).resolve().parents[1], auth_token='')
print(json.dumps({'port':server.server_port}),flush=True)
try: server.serve_forever()
finally: server.server_close();service.close();tmp.cleanup()
