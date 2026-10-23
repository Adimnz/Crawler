"""Offline adjusted-price provider contract; no external requests or real keys."""
import json
import os
import unittest
from urllib.parse import urlsplit, parse_qs
from unittest.mock import patch
from server.financial_connectors import collect_financial_source
from server.connectors import ConnectorError

class Provider:
    def __init__(self):self.calls=[];self.fail=False
    def fetch(self,url,**kwargs):
        self.calls.append(url)
        params=parse_qs(urlsplit(url).query)
        if 'company_tickers' in url:
            body={'fields':['cik','name','ticker','exchange'],'data':[[1,'Synthetic Issuer','FIX','Nasdaq']]}
        elif self.fail:raise RuntimeError('url contains secret '+url)
        elif params.get('function')==['OVERVIEW']:body={'Symbol':'FIX','Currency':'USD'}
        else:body={'Meta Data':{'2. Symbol':'FIX'},'Time Series (Daily)':{'2025-01-02':{'5. adjusted close':'104.25'}}}
        return json.dumps(body).encode(),{},url

class EquityDailyTests(unittest.TestCase):
    def setUp(self):
        self.network=Provider()
        self.source={'kind':'equity_daily','config':{'ticker':'FIX','assetId':'equity:NASDAQ:FIX'}}
        self.env=patch.dict(os.environ,{'SEC_USER_AGENT':'Fixture fixture@example.test','ALPHAVANTAGE_API_KEY':'fixture-secret'})
        self.env.start()
    def tearDown(self):self.env.stop()
    def test_identity_currency_adjustment_and_unknown_historical_availability(self):
        result=collect_financial_source(self.source,self.network)
        row=result['observations'][0]
        self.assertEqual(row['assetId'],'equity:NASDAQ:FIX')
        self.assertEqual(row['currency'],'USD')
        self.assertEqual(row['value'],104.25)
        self.assertEqual(row['adjustment'],'dividend-adjusted')
        self.assertTrue(row['historicalAvailabilityUnknown'])
        self.assertNotIn('availableAt',row)
        self.assertNotIn('fixture-secret',json.dumps({k:v.decode() if isinstance(v,bytes) else v for k,v in result.items()}))
    def test_provider_failure_does_not_expose_secret(self):
        self.network.fail=True
        with self.assertRaises(ConnectorError) as caught:collect_financial_source(self.source,self.network)
        self.assertNotIn('fixture-secret',str(caught.exception))
    def test_ticker_is_never_guessed_from_a_configured_name(self):
        self.source['config']['assetId']='equity:NASDAQ:WRONG'
        with self.assertRaises(ConnectorError):collect_financial_source(self.source,self.network)
        self.assertEqual(len(self.network.calls),1)
