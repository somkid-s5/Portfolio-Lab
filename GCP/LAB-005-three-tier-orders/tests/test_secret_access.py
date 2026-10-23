import importlib.util
from io import BytesIO
import json
from pathlib import Path
import unittest
from urllib.error import HTTPError
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('secret_check',ROOT/'scripts/check-secret-access.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class Response(BytesIO):
    code=200

class FakeOpener:
    def __init__(self,status=403,reason=None,scope=True):
        self.status=status
        self.reason=reason
        self.scope=scope
        self.calls=[]
    def open(self,request,timeout):
        self.calls.append(request)
        url=request.full_url
        if url.startswith(module.META):
            name=url[len(module.META):]
            values={'project/project-id':'test-project',
                    'instance/service-accounts/default/email':'lab005-web@test-project.iam.gserviceaccount.com',
                    'instance/service-accounts/default/scopes':'https://www.googleapis.com/auth/cloud-platform' if self.scope else 'read-only',
                    'instance/service-accounts/default/token':json.dumps({'access_token':'NEVER-PRINT-TOKEN'})}
            return Response(values[name].encode())
        if self.status==200:
            class NeverRead(Response):
                def read(self,*args): raise AssertionError('Secret payload must not be read')
            return NeverRead(b'NEVER-PRINT-SECRET')
        data=json.dumps({'error':{'status':'PERMISSION_DENIED','details':[{'reason':self.reason}]}}).encode()
        raise HTTPError(url,self.status,'fixture',{},BytesIO(data))

class SecretBoundaryTests(unittest.TestCase):
    def test_real_denial_and_unexpected_access(self):
        sa='lab005-web@test-project.iam.gserviceaccount.com'
        denied=module.check('lab005-db','1',sa,FakeOpener())
        self.assertTrue(denied['denied'])
        allowed=module.check('lab005-db','1',sa,FakeOpener(200))
        self.assertFalse(allowed['denied'])
        self.assertNotIn('NEVER-PRINT',json.dumps([denied,allowed]))
    def test_wrong_identity_scope_and_non403_are_not_passes(self):
        sa='lab005-web@test-project.iam.gserviceaccount.com'
        for opener in [FakeOpener(404),FakeOpener(403,'ACCESS_TOKEN_SCOPE_INSUFFICIENT'),FakeOpener(scope=False)]:
            with self.assertRaises(ValueError):
                module.check('lab005-db','1',sa,opener)
        with self.assertRaises(ValueError):
            module.check('lab005-db','1','wrong-sa',FakeOpener())
        with self.assertRaises(ValueError):
            module.check('lab005-db','latest',sa,FakeOpener())
