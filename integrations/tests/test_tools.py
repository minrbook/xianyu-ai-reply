import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from xianyu_tools.client import Client, ToolError, load_credentials, normalize_url, save_credentials
from xianyu_tools.cli import main
from xianyu_tools.mcp_server import create_server

TOKEN = 'test-access-token-with-no-real-credentials'


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.delenv('XIANYU_BASE_URL', raising=False)
    monkeypatch.delenv('XIANYU_ALLOW_WRITES', raising=False)


@pytest.mark.parametrize('url', [
    'http://example.test', 'https://user:secret@example.test',
    'https://example.test?token=private', 'https://example.test/#private',
    'https://example.test/api', 'file:///tmp/private', 'https://example.test:bad',
    'https://example.test\\@evil.test',
])
def test_reject_unsafe_urls(url):
    with pytest.raises(ToolError):
        normalize_url(url)


def test_credentials_private_and_origin_bound(tmp_path, monkeypatch):
    save_credentials('https://example.test/', TOKEN)
    path = tmp_path / '.config/xianyu-ai-reply/credentials.json'
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert load_credentials()['access_token'] == TOKEN
    assert Client.from_environment().base_url == 'https://example.test'
    monkeypatch.setenv('XIANYU_BASE_URL', 'https://other.test')
    with pytest.raises(ToolError, match='绑定'):
        Client.from_environment()
    path.chmod(0o644)
    with pytest.raises(ToolError, match='600'):
        load_credentials()


def test_symlink_credentials_rejected(tmp_path):
    target = tmp_path / 'untouched'
    target.write_text('original')
    directory = tmp_path / '.config/xianyu-ai-reply'
    directory.mkdir(parents=True)
    (directory / 'credentials.json').symlink_to(target)
    with pytest.raises(ToolError, match='符号链接'):
        save_credentials('https://example.test', TOKEN)
    assert target.read_text() == 'original'


def client_for(handler, writes=False):
    return Client('https://example.test', TOKEN, allow_writes=writes, transport=httpx.MockTransport(handler))


def test_response_filter_and_account_safe_endpoint():
    def handler(request):
        assert request.url.path == '/api/v1/cookies/options'
        assert request.headers['Authorization'] == 'Bearer ' + TOKEN
        return httpx.Response(200, json=[{'id': 'account-1', 'enabled': True, 'cookie': 'private', 'login_password': 'private', 'remark': 'private'}])
    assert client_for(handler).accounts() == [{'id': 'account-1', 'enabled': True}]


def test_order_pagination_and_pii_filter():
    def handler(request):
        assert request.url.path == '/api/v1/orders'
        assert dict(request.url.params) == {'cookie_id': 'account-1', 'page': '2', 'page_size': '5', 'status': 'paid'}
        return httpx.Response(200, json={'success': True, 'data': [{'order_id': 'order-1', 'amount': '9.00', 'receiver_address': 'private', 'buyer_id': 'private', 'delivery_content': 'private', 'title': {'token': 'private'}}], 'total': 7, 'page': 2})
    output = client_for(handler).orders('account-1', 2, 5, 'paid')
    assert output['data'] == [{'order_id': 'order-1', 'amount': '9.00'}]
    assert 'private' not in json.dumps(output)


@pytest.mark.parametrize('status,body', [(200, {'success': False, 'message': TOKEN}), (401, {'token': TOKEN}), (500, {'error': TOKEN}), (200, {'code': 40001, 'detail': TOKEN})])
def test_error_bodies_never_exposed(status, body):
    with pytest.raises(ToolError) as error:
        client_for(lambda _: httpx.Response(status, json=body)).accounts()
    assert TOKEN not in str(error.value)


def test_no_redirect_or_retry():
    calls = []
    def redirect(request):
        calls.append(request)
        return httpx.Response(302, headers={'location': 'https://other.test/'})
    with pytest.raises(ToolError):
        client_for(redirect).accounts()
    assert len(calls) == 1
    calls.clear()
    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout('secret=' + TOKEN)
    with pytest.raises(ToolError) as error:
        client_for(timeout, True).send_message('account-1', 'chat', 'buyer', 'hello', True)
    assert len(calls) == 1 and TOKEN not in str(error.value)


def test_writes_require_both_opt_in_and_confirmation():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'success': True, 'message': TOKEN})
    with pytest.raises(ToolError):
        client_for(handler).send_message('a', 'chat', 'buyer', 'hello', True)
    with pytest.raises(ToolError):
        client_for(handler, True).send_message('a', 'chat', 'buyer', 'hello')
    assert not requests
    assert client_for(handler, True).send_message('a', 'chat', 'buyer', 'hello', True) == {'success': True}
    assert json.loads(requests[0].content) == {'cookie_id': 'a', 'chat_id': 'chat', 'to_user_id': 'buyer', 'message': 'hello'}


def test_keywords_replace_explicit_payload_and_validation():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[] if request.method == 'GET' else {'success': True})
    client = client_for(handler, True)
    for rows in ([], [{'keyword': 'k', 'reply': 'r', 'cookie': 'private'}]):
        with pytest.raises(ToolError):
            client.replace_keywords('a', rows, True)
    assert not requests
    client.replace_keywords('a', [{'keyword': 'k', 'reply': 'r'}], True)
    assert len(requests) == 2 and requests[0].method == 'GET'
    assert requests[1].method == 'POST'
    assert requests[1].url.path == '/api/v1/keywords-with-item-id/a'
    assert json.loads(requests[1].content) == {'keywords': [{'keyword': 'k', 'reply': 'r', 'type': 'text'}]}


@pytest.mark.parametrize('account', ['../admin', 'a/b', 'a?token=x', 'a\n'])
def test_account_path_injection_rejected(account):
    def never(_):
        pytest.fail('must reject before network')
    with pytest.raises(ToolError):
        client_for(never).keywords(account)


def test_cli_json_error_without_private_path(capsys):
    assert main(['accounts']) == 1
    result = capsys.readouterr()
    assert result.out == ''
    assert json.loads(result.err)['success'] is False
    assert str(Path.home()) not in result.err


def test_cli_auth_stdin_validates_and_does_not_echo(monkeypatch, capsys):
    import io
    monkeypatch.setattr(sys, 'stdin', io.StringIO(TOKEN))
    monkeypatch.setattr(Client, 'whoami', lambda _: {'authenticated': True})
    assert main(['--url', 'https://example.test', 'auth', 'set-token', '--stdin']) == 0
    captured = capsys.readouterr()
    assert TOKEN not in captured.out + captured.err
    assert load_credentials()['access_token'] == TOKEN
    assert main(['auth', 'clear']) == 0
    assert not load_credentials()


def test_cli_packaged_entrypoint():
    result = subprocess.run([str(Path(sys.executable).parent / 'xianyu'), '--help'], capture_output=True, text=True)
    assert result.returncode == 0 and 'account-status' in result.stdout


@pytest.mark.asyncio
async def test_mcp_tool_sets_and_annotations():
    read = await create_server(Client('https://example.test')).list_tools()
    assert {t.name for t in read} == {'health', 'whoami', 'list_accounts', 'list_items', 'list_orders', 'list_keywords'}
    assert all(t.annotations.readOnlyHint for t in read)
    write = await create_server(Client('https://example.test', allow_writes=True)).list_tools()
    tools = {t.name: t for t in write}
    assert len(tools) == 9
    assert tools['send_message'].annotations.idempotentHint is False
    assert tools['replace_keywords'].annotations.destructiveHint is True
    assert not tools['send_message'].annotations.readOnlyHint


@pytest.mark.asyncio
async def test_stdio_protocol_end_to_end(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == '/api/v1/cookies/options'
            assert self.headers['Authorization'] == 'Bearer ' + TOKEN
            content = json.dumps([{'id': 'account-1', 'enabled': True, 'cookie': 'must-not-return'}]).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        def log_message(self, *args):
            pass
    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    save_credentials(f'http://127.0.0.1:{http.server_port}', TOKEN)
    params = StdioServerParameters(command=sys.executable, args=['-m', 'xianyu_tools.mcp_server'], env={'HOME': str(tmp_path), 'XIANYU_ALLOW_WRITES': '0'})
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                assert len(listed.tools) == 6
                result = await session.call_tool('list_accounts', {})
                assert not result.isError
                rendered = str(result)
                assert 'account-1' in rendered and 'must-not-return' not in rendered and TOKEN not in rendered
                rejected = await session.call_tool('send_message', {'account_id': 'a'})
                assert rejected.isError
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=2)


def test_items_match_backend_fields():
    def handler(request):
        assert request.url.path == '/api/v1/items/paginated'
        return httpx.Response(200, json={'success': True, 'data': [{'item_id': 'item-1', 'item_price': '8.00', 'item_quantity': 2, 'item_status_desc': '在线', 'item_detail': {'cookie': 'private'}}]})
    assert client_for(handler).items()['data'] == [{'item_id': 'item-1', 'item_price': '8.00', 'item_quantity': 2, 'item_status_desc': '在线'}]


@pytest.mark.parametrize('body', [{}, [], {'status': 'ok'}])
def test_write_requires_explicit_server_success(body):
    with pytest.raises(ToolError, match='未明确确认'):
        client_for(lambda _: httpx.Response(200, json=body), True).set_account_enabled('a', True, True)


def test_keywords_preserve_unsupported_rule_types():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[{'keyword': 'contact', 'type': 'external_contact'}])
    with pytest.raises(ToolError, match='特殊规则'):
        client_for(handler, True).replace_keywords('a', [{'keyword': 'k', 'reply': 'r'}], True)
    assert len(calls) == 1 and calls[0].method == 'GET'
