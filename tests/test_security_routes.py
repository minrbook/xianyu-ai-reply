import importlib
import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from common.models.user import User, UserStatus, UserRole
from common.models.xy_account import XYAccount
from common.utils.credential_crypto import credential_cipher
from common.core.config import get_settings
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent

def load_app(monkeypatch, service, module):
    # Each service uses the same top-level package name. Isolate namespaces without
    # importing unrelated startup code or connecting to databases/browser services.
    for name in list(sys.modules):
        if name == 'app' or name.startswith('app.'):
            monkeypatch.delitem(sys.modules, name)
    for name in ['app','app.api','app.api.routes','app.core','app.services']:
        package = types.ModuleType(name)
        package.__path__ = [str(ROOT / service / name.replace('.', '/'))]
        monkeypatch.setitem(sys.modules, name, package)
    return importlib.import_module(module)

@pytest.mark.asyncio
async def test_message_auth_ownership_and_rate_limit(monkeypatch, tmp_path):
    key=tmp_path/'key'; key.write_bytes(Fernet.generate_key())
    monkeypatch.setattr(get_settings(),'credential_encryption_key_file',str(key)); credential_cipher.cache_clear()
    route=load_app(monkeypatch,'backend-web','app.api.routes.message')
    deps=importlib.import_module('app.api.deps')
    security=importlib.import_module('app.core.security')
    monkeypatch.setattr(security.get_settings(),'jwt_secret_key','test-secret-'+'x'*64)
    engine=create_async_engine('sqlite+aiosqlite://')
    async with engine.begin() as c:
        await c.run_sync(lambda conn: User.__table__.create(conn))
        await c.run_sync(lambda conn: XYAccount.__table__.create(conn))
    async with async_sessionmaker(engine,expire_on_commit=False)() as session:
        session.add(User(id=1,username='owner',email='owner@example.test',password_hash='unused',role=UserRole.MEMBER,status=UserStatus.ACTIVE))
        session.add(User(id=2,username='other',email='other@example.test',password_hash='unused',role=UserRole.MEMBER,status=UserStatus.ACTIVE))
        session.add(XYAccount(id=1,owner_id=1,account_id='owned',cookie='unb=123',login_method='cookie',status='active'))
        await session.commit()
        app=FastAPI(); app.include_router(route.router,prefix='/api/v1/messages')
        async def db():yield session
        app.dependency_overrides[deps.get_db_session]=db
        class Redis:
            count=0
            async def eval(self,*args):self.count+=1; return self.count
        redis=Redis()
        async def get_redis():return redis
        monkeypatch.setattr(route,'get_redis_client',get_redis)
        sent=[]
        async def send(**kwargs):sent.append(kwargs); return {'success':True}
        module=types.ModuleType('app.services.websocket_client'); module.websocket_client=SimpleNamespace(send_message=send)
        monkeypatch.setitem(sys.modules,module.__name__,module)
        payload={'cookie_id':'owned','chat_id':'chat','to_user_id':'buyer','message':'test'}
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
            assert (await client.post('/api/v1/messages/send',json={**payload,'api_key':'xianyu_api_secret_2024'})).status_code == 401
            def auth(user):return {'Authorization':'Bearer '+security.create_access_token(str(user))}
            assert (await client.post('/api/v1/messages/send',json=payload,headers=auth(2))).status_code==403
            refresh={'Authorization':'Bearer '+security.create_refresh_token('1')}
            assert (await client.post('/api/v1/messages/send',json=payload,headers=refresh)).status_code==401
            response=await client.post('/api/v1/messages/send',json=payload,headers=auth(1))
            assert response.status_code==200 and response.json()['success']
            assert len(sent)==1
            for bad in ['owned\\n', '../owned', 'owned%2fother']:
                assert (await client.post('/api/v1/messages/send',json={**payload,'cookie_id':bad},headers=auth(1))).status_code==422
            assert len(sent)==1
            redis.count=30
            assert (await client.post('/api/v1/messages/send',json=payload,headers=auth(1))).status_code==429
            assert len(sent)==1
            async def fail():raise RuntimeError('redis offline')
            monkeypatch.setattr(route,'get_redis_client',fail)
            assert (await client.post('/api/v1/messages/send',json=payload,headers=auth(1))).status_code==503
            assert len(sent)==1
    await engine.dispose(); credential_cipher.cache_clear()

def test_password_login_requires_internal_token_and_owner(monkeypatch):
    route=load_app(monkeypatch,'websocket','app.api.routes.password_login')
    deps=importlib.import_module('app.api.deps')
    monkeypatch.setattr(deps.get_settings(),'internal_api_token','a'*48)
    app=FastAPI();app.include_router(route.router)
    started=[]
    monkeypatch.setattr(route,'_start_password_login_thread',lambda **kw:started.append(kw))
    state=types.ModuleType('app.services.captcha.password_login_state')
    state.password_login_state=SimpleNamespace(start_processing=lambda _:True,finish_processing=lambda _:None)
    monkeypatch.setitem(sys.modules,state.__name__,state)
    client=TestClient(app)
    payload={'account_id':'owned','account':'dummy','password':'dummy','user_id':1}
    assert client.post('/password-login',json=payload).status_code==401
    assert client.post('/password-login',json=payload,headers={'X-Internal-Token':'bad'}).status_code==401
    assert not started
    headers={'X-Internal-Token':'a'*48}
    response=client.post('/password-login',json=payload,headers=headers)
    assert response.status_code==200 and response.json()['success']
    sid=response.json()['session_id']
    assert len(started)==1
    assert client.get(f'/password-login/check/{sid}',params={'user_id':2},headers=headers).json()['status']=='not_found'
    assert not client.delete(f'/password-login/cancel/{sid}',params={'user_id':2},headers=headers).json()['success']
    assert client.get(f'/password-login/check/{sid}',params={'user_id':1},headers=headers).json()['status']=='processing'

@pytest.mark.asyncio
async def test_encrypted_token_conditional_invalidation(monkeypatch, tmp_path):
    from datetime import datetime, timedelta
    from common.models.token_cache import TokenCache
    from common.services import token_renewal_cache_service as service
    key=tmp_path/'key';key.write_bytes(Fernet.generate_key())
    monkeypatch.setattr(get_settings(),'credential_encryption_key_file',str(key));credential_cipher.cache_clear()
    engine=create_async_engine('sqlite+aiosqlite://')
    async with engine.begin() as c:
        await c.run_sync(lambda conn: TokenCache.__table__.create(conn))
    maker=async_sessionmaker(engine,expire_on_commit=False)
    monkeypatch.setattr(service,'async_session_maker',maker)
    future=datetime.now()+timedelta(days=1)
    async with maker() as s:
        s.add(TokenCache(id=1,user_id='123',token='current-secret',device_id='device',expire_at=future))
        await s.commit()
    unchanged=await service.mark_token_cache_expired(token_user_id='123',expected_token='old-secret')
    assert unchanged.success and not unchanged.changed
    changed=await service.mark_token_cache_expired(token_user_id='123',expected_token='current-secret')
    assert changed.success and changed.changed
    await engine.dispose();credential_cipher.cache_clear()

@pytest.mark.asyncio
async def test_admin_bootstrap_fails_without_secret(monkeypatch):
    from common.db import init_database as initialization
    engine=create_async_engine('sqlite+aiosqlite://')
    from sqlalchemy import text
    async with engine.begin() as c:
        await c.execute(text('CREATE TABLE xy_users(id INTEGER PRIMARY KEY,username TEXT,password_hash TEXT)'))
    monkeypatch.setattr(initialization,'async_session_maker',async_sessionmaker(engine))
    monkeypatch.delenv('INITIAL_ADMIN_PASSWORD_FILE',raising=False)
    with pytest.raises(RuntimeError,match='INITIAL_ADMIN_PASSWORD_FILE'):
        await initialization.DatabaseInitializer().create_default_admin()
    await engine.dispose()
