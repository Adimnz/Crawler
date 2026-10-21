"""Supabase contract fixtures; no email, provider, or paid API requests."""
from pathlib import Path
import base64
import copy
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.accounts import AccountAuth
from server.connectors import ConnectorError
from server.service import ResearchService


def token(aal='aal1', user='alice'):
    segment=base64.urlsafe_b64encode(json.dumps({'sub':user,'aal':aal}).encode()).decode().rstrip('=')
    return 'fixture.'+segment+'.signature'


class AuthProvider:
    def __init__(self):
        self.user={'id':'fixture-alice','email':'alice@example.test','email_confirmed_at':'2026-10-19T00:00:00Z','user_metadata':{'display_name':'Alice'},'factors':[]}
        self.requests=[]
        self.verified=False
        self.fail=None
    def fetch(self,url,headers=None,method='GET',body=None,**kwargs):
        self.requests.append({'url':url,'method':method,'body':json.loads(body) if body else None,'headers':headers})
        if self.fail: raise ConnectorError('Provider secret must never escape',status=self.fail)
        if url.endswith('/settings'): result={'external':{'email':True}}
        elif '/token?' in url or url.endswith('/verify') or url.endswith('/factors/fixture-factor/verify'):
            if url.endswith('/factors/fixture-factor/verify'): self.verified=True
            result={'access_token':token('aal2' if self.verified else 'aal1'),'refresh_token':'fixture-private-refresh-token','expires_in':3600,'user':self.user}
        elif url.endswith('/user'):
            if headers.get('Authorization') not in {'Bearer '+token(),'Bearer '+token('aal2')}: raise ConnectorError('Invalid fixture token',status=401)
            if method=='PUT' and body:
                content=json.loads(body)
                if 'data' in content:self.user['user_metadata']=content['data']
            result=copy.deepcopy(self.user)
            if self.verified:result['factors']=[{'id':'fixture-factor','factor_type':'totp','status':'verified','friendly_name':'Authenticator'}]
        elif url.endswith('/factors/fixture-factor/challenge'):result={'id':'fixture-challenge'}
        elif url.endswith('/factors'):
            result={'id':'fixture-factor','totp':{'secret':'FIXTURE-TOTP-SECRET','uri':'otpauth://totp/Fixture'}}
        else:result={}
        return json.dumps(result).encode(),{'content-type':'application/json'},url


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.provider=AuthProvider()
        self.s=ResearchService(self.tmp.name,network=self.provider,seed=False,dsn='')
        self.auth=self.s.accounts
        self.auth.url='https://fixtureproject.supabase.co'
        self.auth.key='fixture-publishable-public-key'
    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()
    def login(self,remember=False):
        result,secret=self.auth.action('login',{'email':'alice@example.test','password':'fixture-password-123','remember':remember})
        return result,secret,self.auth.session(secret)

    def test_setup_verifies_project_without_exposing_key(self):
        result=self.auth.setup({'projectURL':'https://fixtureproject.supabase.co','publishableKey':'fixture-new-publishable-key'})
        self.assertTrue(result['configured'])
        self.assertNotIn('fixture-new-publishable-key',json.dumps(result))
        reloaded=AccountAuth(self.s,self.tmp.name)
        self.assertEqual(reloaded.key,'fixture-new-publishable-key')

    def test_setup_rejects_embedded_credentials_and_private_or_secret_key_configuration(self):
        for url in ('http://fixtureproject.supabase.co','https://127.0.0.1','https://evil.example','https://user:password@fixtureproject.supabase.co','https://fixtureproject.supabase.co/path'):
            with self.subTest(url=url),self.assertRaises(ValueError):self.auth.setup({'projectURL':url,'publishableKey':'fixture-public-key'})
        with self.assertRaises(ValueError):self.auth.setup({'projectURL':self.auth.url,'publishableKey':'sb_secret_private-service-key'})

    def test_provider_failure_messages_are_sanitized(self):
        for status in (400,401,403,404,429,503):
            self.provider.fail=status
            with self.subTest(status=status),self.assertRaises(ValueError) as error:self.login()
            self.assertNotIn('Provider secret',str(error.exception))

    def test_signup_preserves_display_name_and_requires_confirmation_and_terms(self):
        body={'email':'alice@example.test','password':'fixture-password-123','confirmPassword':'fixture-password-123','displayName':'Alice','acceptTerms':True}
        result,secret=self.auth.action('register',body,callback='http://localhost:8765/CRAWLER/account.html?view=callback')
        self.assertIsNone(secret)
        self.assertIn('verify',result['message'])
        self.assertEqual(self.provider.requests[-1]['body']['data']['display_name'],'Alice')
        self.assertFalse(self.auth.sessions)
        with self.assertRaises(ValueError):self.auth.action('register',{**body,'acceptTerms':False})
        with self.assertRaises(ValueError):self.auth.action('register',{**body,'confirmPassword':'different'})

    def test_login_uses_provider_verified_identity_and_returns_no_tokens(self):
        result,secret,session=self.login()
        self.assertEqual(result['user']['id'],'fixture-alice')
        self.assertEqual(session['user']['id'],'fixture-alice')
        self.assertNotIn('fixture-private-refresh-token',json.dumps(result))
        self.assertNotIn(secret,json.dumps(result))
        self.assertIsNone(self.auth.session('tampered-cookie'))

    def test_unverified_account_and_forged_client_user_identity_are_rejected(self):
        self.provider.user['email_confirmed_at']=None
        with self.assertRaises(ValueError):self.login()
        with self.assertRaises(ValueError):self.auth.establish({'access_token':'forged','refresh_token':'forged','user':{'id':'another-user'}})

    def test_remembered_sessions_persist_across_restart_with_private_storage(self):
        self.auth.setup({'projectURL':self.auth.url,'publishableKey':self.auth.key})
        _,secret,session=self.login(True)
        reloaded=AccountAuth(self.s,self.tmp.name)
        self.assertEqual(reloaded.session(secret)['user']['id'],'fixture-alice')
        if os.name=='nt':self.assertNotIn(b'fixture-private-refresh-token',(Path(self.tmp.name)/'account-sessions.json').read_bytes())
        self.assertTrue(session['remember'])

    def test_provider_refresh_rotation_is_retained(self):
        _,secret,session=self.login()
        session['providerExpires']=0
        self.assertEqual(self.auth.session(secret)['user']['id'],'fixture-alice')
        self.assertTrue(any('grant_type=refresh_token' in r['url'] for r in self.provider.requests))
        self.assertGreater(session['providerExpires'],0)

    def test_recovery_uses_one_time_verification_and_never_stores_password(self):
        result,_=self.auth.action('recover',{'email':'alice@example.test'},callback='http://localhost/CRAWLER/account.html?view=callback')
        self.assertIn('eligible',result['message'])
        result,secret=self.auth.action('verify',{'email':'alice@example.test','type':'recovery','code':'123456'})
        self.assertTrue(result['recovery'])
        self.assertTrue(self.auth.session(secret))
        result,_=self.auth.action('password',{'password':'replacement-password-123','confirmPassword':'replacement-password-123'},self.auth.session(secret))
        self.assertNotIn('replacement-password',json.dumps(self.auth.sessions))

    def test_logout_and_session_revocation_do_not_affect_other_users(self):
        _,first,session=self.login()
        _,second,other=self.login()
        self.auth.action('logout',{'others':True},session)
        self.assertIsNone(self.auth.session(second))
        self.assertTrue(self.auth.session(first))
        self.auth.action('logout',{},session)
        self.assertIsNone(self.auth.session(first))

    def test_multifactor_is_required_until_aal2_verification(self):
        self.provider.user['factors']=[{'id':'fixture-factor','factor_type':'totp','status':'verified'}]
        result,secret,session=self.login()
        self.assertTrue(result['needsMfa'])
        with self.assertRaises(ValueError):self.auth.action('profile',{'displayName':'Changed'},session)
        challenge,_=self.auth.action('mfa-challenge',{'factorId':'fixture-factor'},session)
        result,_=self.auth.action('mfa-verify',{'factorId':'fixture-factor','challengeId':challenge['challengeId'],'code':'123456'},session)
        self.assertFalse(result['needsMfa'])
        self.assertEqual(self.auth._aal(session['access']),'aal2')

    def test_rate_limiting_bounds_repeated_authentication_attempts(self):
        for _ in range(8):self.auth.limit('fixture-ip','login')
        with self.assertRaises(ValueError):self.auth.limit('fixture-ip','login')
        self.auth.limit('another-ip','login')

    def test_account_deletion_requires_exact_confirmation_and_revokes_private_sessions(self):
        _,secret,session=self.login()
        with self.assertRaises(ValueError):self.auth.action('delete',{'confirmation':'wrong@example.test'},session)
        result,_=self.auth.action('delete',{'confirmation':'alice@example.test'},session)
        self.assertTrue(result['deleted'])
        self.assertIsNone(self.auth.session(secret))
        self.assertTrue(any('/rest/v1/rpc/delete_own_account' in r['url'] for r in self.provider.requests))


if __name__=='__main__':unittest.main()
