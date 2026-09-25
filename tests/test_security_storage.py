import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text, Table, Column, Integer, MetaData, select
from common.utils import credential_crypto as crypto
from common.utils.account_identity import require_same_account_identity
from common.utils.remote_security import require_trusted_remote
from common.core.config import get_settings

@pytest.fixture(autouse=True)
def key(tmp_path, monkeypatch):
    keyfile = tmp_path / 'key'
    keyfile.write_bytes(Fernet.generate_key())
    monkeypatch.setattr(get_settings(), 'credential_encryption_key_file', str(keyfile))
    crypto.credential_cipher.cache_clear()
    yield keyfile
    crypto.credential_cipher.cache_clear()

def test_encrypted_storage_and_integrity(key):
    engine = create_engine('sqlite://')
    metadata = MetaData()
    t = Table('credentials', metadata, Column('id', Integer, primary_key=True), Column('secret', crypto.EncryptedText()), Column('meta', crypto.AccountMetadata()))
    metadata.create_all(engine)
    value = 'unb=123; sgcookie=private-value'
    snapshot = {'cookies_refresh_snapshot': [{'name':'sgcookie','value':'private-value'}], 'other':123}
    with engine.begin() as c:
        c.execute(t.insert().values(id=1, secret=value, meta=snapshot))
        raw = c.execute(text('SELECT secret,meta FROM credentials')).one()
        assert value not in raw.secret and 'private-value' not in raw.meta
        assert c.execute(select(t.c.secret)).scalar_one() == value
        assert c.execute(select(t.c.meta)).scalar_one() == snapshot
    encrypted = crypto.encrypt_credential(value)
    key.write_bytes(Fernet.generate_key()); crypto.credential_cipher.cache_clear()
    with pytest.raises(RuntimeError, match='解密失败'):
        crypto.decrypt_credential(encrypted)

def test_no_plaintext_fallback(monkeypatch):
    with pytest.raises(RuntimeError, match='明文'):
        crypto.decrypt_credential('plaintext')
    monkeypatch.setattr(get_settings(), 'credential_encryption_key_file', '')
    crypto.credential_cipher.cache_clear()
    with pytest.raises(RuntimeError, match='必须配置'):
        crypto.encrypt_credential('secret')

def test_migration_idempotent_and_fail_closed():
    from scripts.migrate_credentials import migrate
    e=create_engine('sqlite://')
    with e.begin() as c:
        c.execute(text('CREATE TABLE xy_accounts (id INTEGER PRIMARY KEY,cookie TEXT,login_password TEXT,metadata JSON)'))
        c.execute(text('INSERT INTO xy_accounts VALUES(1,:cookie,:password,:metadata)'), {'cookie':'unb=123; token=secret','password':'a-secret-password','metadata':json.dumps({'cookies_refresh_snapshot':[{'name':'token','value':'secret'}]})})
        with pytest.raises(RuntimeError, match='明文'):
            migrate(c, verify_only=True)
        assert migrate(c) == 1
        row = c.execute(text('SELECT cookie,login_password,metadata FROM xy_accounts')).one()
        assert crypto.decrypt_credential(row.cookie) == 'unb=123; token=secret'
        assert 'a-secret-password' not in row.login_password
        assert '"value": "secret"' not in row.metadata
        assert migrate(c) == 0
        assert migrate(c, verify_only=True) == 0

def test_identity_cannot_be_replaced():
    require_same_account_identity(SimpleNamespace(unb='123'), '123')
    with pytest.raises(ValueError):require_same_account_identity(SimpleNamespace(unb='123'), '456')
    with pytest.raises(ValueError):require_same_account_identity(None, '')

@pytest.mark.parametrize('url',['http://trusted.example/path','https://evil.example/path','https://trusted.example.evil/path','https://trusted.example@evil.example/path'])
def test_remote_deny_untrusted(url, monkeypatch):
    monkeypatch.setattr(get_settings(),'remote_credential_origins','https://trusted.example')
    with pytest.raises(ValueError):require_trusted_remote(url)

def test_remote_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(get_settings(),'remote_credential_origins','')
    with pytest.raises(ValueError):require_trusted_remote('https://trusted.example/path')
    monkeypatch.setattr(get_settings(),'remote_credential_origins','https://trusted.example')
    require_trusted_remote('https://trusted.example/path')


def test_log_redaction():
    from common.utils.logging_utils import redact_log_record
    for text_value in ["headers: {'Cookie': 'unb=123; sgcookie=do-not-log'}", "password=do-not-log", "https://host/?api_key=do-not-log"]:
        record={"message": text_value,"exception":None}
        redact_log_record(record)
        assert 'do-not-log' not in record['message']

def test_unsigned_update_disabled():
    from launcher.updater import download_update, apply_update
    assert not download_update('anything.zip')['success']
    assert not apply_update('/does/not/exist.zip')['success']

def test_deployment_is_local_and_has_no_internal_ports():
    import yaml
    config=yaml.safe_load((Path(__file__).resolve().parent.parent/'docker-compose.yml').read_text())
    for name in ['backend-web','websocket','scheduler']:
        service=config['services'][name]
        assert not service.get('ports')
        assert 'build' in service and 'image' not in service
        assert 'credential_key' in service['secrets']
    assert config['services']['frontend']['ports'][0].startswith('127.0.0.1:')

def test_prepare_env_preserves_secrets(tmp_path):
    import subprocess, sys, shutil
    scripts=tmp_path/'scripts';scripts.mkdir()
    source=Path(__file__).resolve().parent.parent/'scripts/prepare_secure_env.py'
    shutil.copy(source,scripts/source.name)
    subprocess.run([sys.executable,str(scripts/source.name)],check=True,capture_output=True)
    key=tmp_path/'.secrets/credential_key';original=key.read_bytes()
    env=(tmp_path/'.env').read_bytes()
    subprocess.run([sys.executable,str(scripts/source.name)],check=True,capture_output=True)
    assert key.read_bytes()==original and (tmp_path/'.env').read_bytes()==env
    assert key.stat().st_mode & 0o777 == 0o600
    key.unlink()
    assert subprocess.run([sys.executable,str(scripts/source.name)],capture_output=True).returncode!=0

@pytest.mark.asyncio
async def test_auth_secrets_are_derived_and_separated(key):
    from common.utils.credential_crypto import derive_service_secret
    from common.utils.internal_token_service import ensure_internal_api_token, load_internal_api_token
    jwt=derive_service_secret('jwt:backend-web')
    internal=derive_service_secret('internal-api')
    assert jwt != internal and len(jwt)==64
    assert derive_service_secret('jwt:backend-web') == jwt
    settings=SimpleNamespace(internal_api_token='old-public-token')
    assert await ensure_internal_api_token(settings)==internal
    assert await load_internal_api_token(settings)==internal


def test_geetest_requires_deployer_credentials(monkeypatch):
    from common.services.geetest import GeetestConfig, GeetestLib
    monkeypatch.setattr(GeetestConfig, 'CAPTCHA_ID', '')
    monkeypatch.setattr(GeetestConfig, 'PRIVATE_KEY', '')
    with pytest.raises(ValueError, match='GEETEST_CAPTCHA_ID'):
        GeetestLib()
    with pytest.raises(ValueError, match='GEETEST_PRIVATE_KEY'):
        GeetestLib(captcha_id='test-captcha-id')
    client = GeetestLib(captcha_id='test-captcha-id', private_key='test-only-secret')
    assert client.captcha_id == 'test-captcha-id'
