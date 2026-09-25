"""Small, explicit API surface with private local credentials and filtered output."""
from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from urllib.parse import urlsplit, urlunsplit

import httpx


class ToolError(Exception):
    """Public error text must never contain response bodies, URLs or credentials."""


def normalize_url(value: str) -> str:
    if not isinstance(value, str):
        raise ToolError('服务地址必须是字符串。')
    try:
        parts = urlsplit(value)
        host, port = parts.hostname, parts.port
        if not host or parts.username is not None or parts.password is not None:
            raise ValueError
        if parts.query or parts.fragment or parts.path not in ('', '/'):
            raise ValueError
        if any(c.isspace() for c in value) or '\\' in value:
            raise ValueError
        loopback = host == 'localhost'
        try:
            loopback = loopback or ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
        if parts.scheme != 'https' and not (parts.scheme == 'http' and loopback):
            raise ValueError
        netloc = f'[{host}]' if ':' in host else host
        if port is not None:
            netloc += f':{port}'
        return urlunsplit((parts.scheme, netloc, '', '', ''))
    except ValueError:
        raise ToolError('服务地址必须是 HTTPS 根地址；仅回环地址可使用 HTTP，不能含用户信息、查询参数或片段。') from None


def credential_path() -> Path:
    # Never write connection settings or credentials into the checkout.
    return Path.home() / '.config' / 'xianyu-ai-reply' / 'credentials.json'


def _check_path(path: Path) -> None:
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ToolError('凭据路径不能经过符号链接。')


def load_credentials() -> dict:
    path = credential_path()
    _check_path(path)
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 32768:
            raise ToolError('本地凭据文件无效。')
        if os.name == 'posix' and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise ToolError('凭据文件必须属于当前用户且权限为 600。')
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError
        return {'base_url': normalize_url(data['base_url']), 'access_token': validate_token(data['access_token'])}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, KeyError, TypeError):
        raise ToolError('无法读取本地凭据，请重新执行 auth set-token。') from None


def validate_token(token: str) -> str:
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{20,16384}', token):
        raise ToolError('访问令牌格式无效。')
    return token


def save_credentials(base_url: str, token: str) -> None:
    base_url, token = normalize_url(base_url), validate_token(token)
    path = credential_path()
    _check_path(path)
    temp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        fd, temp = tempfile.mkstemp(prefix='.credentials-', dir=path.parent)
        with os.fdopen(fd, 'w') as stream:
            json.dump({'base_url': base_url, 'access_token': token}, stream)
        os.replace(temp, path)
    except OSError:
        raise ToolError('无法保存本地凭据。') from None
    finally:
        if temp is not None:
            Path(temp).unlink(missing_ok=True)


def clear_credentials() -> None:
    path = credential_path()
    _check_path(path)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        raise ToolError('无法删除本地凭据。') from None


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value):
        raise ToolError('账号 ID 格式无效。')
    return value


def project(data: dict, fields: tuple[str, ...]) -> dict:
    if not isinstance(data, dict):
        raise ToolError('服务返回的数据格式不兼容。')
    # Only scalar fields: a future nested field must not expose credentials by accident.
    return {key: data[key] for key in fields if key in data and isinstance(data[key], (str, int, float, bool, type(None)))}


class Client:
    def __init__(self, base_url: str, token: str = '', *, allow_writes: bool = False,
                 transport: httpx.BaseTransport | None = None):
        self.base_url = normalize_url(base_url)
        self.token = validate_token(token) if token else ''
        self.allow_writes = allow_writes
        self.transport = transport

    @classmethod
    def from_environment(cls, base_url: str | None = None) -> Client:
        saved = load_credentials()
        url = normalize_url(base_url or os.environ.get('XIANYU_BASE_URL') or saved.get('base_url') or 'http://127.0.0.1:9000')
        if saved and url != saved['base_url']:
            raise ToolError('服务地址与令牌绑定地址不同，请为新地址重新执行 auth set-token。')
        return cls(url, saved.get('access_token', ''), allow_writes=os.environ.get('XIANYU_ALLOW_WRITES') == '1')

    def _request(self, method: str, path: str, *, params=None, body=None, auth=True):
        if auth and not self.token:
            raise ToolError('尚未配置访问令牌，请执行 auth set-token。')
        headers = {'Authorization': f'Bearer {self.token}'} if auth else {}
        try:
            # No redirects, ambient proxy credentials, cookies, or retry of writes.
            with httpx.Client(timeout=20, follow_redirects=False, trust_env=False, transport=self.transport) as http:
                with http.stream(method, self.base_url + path, headers=headers, params=params, json=body) as response:
                    if response.status_code in (401, 403):
                        raise ToolError('认证失败或没有操作权限；令牌可能已过期。')
                    if not 200 <= response.status_code < 300:
                        raise ToolError(f'服务请求失败（HTTP {response.status_code}），不会自动重试。')
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 4 * 1024 * 1024:
                            raise ToolError('服务响应过大，请缩小查询范围。')
            data = json.loads(content)
        except (httpx.HTTPError, ValueError):
            raise ToolError('无法取得有效服务响应；请检查连接与服务状态。写操作结果不确定时先查询，不要重复执行。') from None
        if isinstance(data, dict) and (data.get('success') is False or ('code' in data and data['code'] not in (0, 200, '200'))):
            raise ToolError('服务拒绝操作；请检查权限、参数、限流或服务日志。')
        if method != 'GET' and (not isinstance(data, dict) or data.get('success') is not True):
            raise ToolError('服务未明确确认写操作成功，请先查询状态，不要重复执行。')
        return data

    def _write(self, confirm: bool) -> None:
        if not self.allow_writes:
            raise ToolError('写操作未启用；需设置 XIANYU_ALLOW_WRITES=1。')
        if confirm is not True:
            raise ToolError('此操作会修改数据或发送真实消息，必须明确确认。')

    def health(self) -> dict:
        data = self._request('GET', '/health', auth=False)
        return project(data, ('status', 'service', 'version'))

    def whoami(self) -> dict:
        data = self._request('GET', '/api/v1/auth/verify')
        if not isinstance(data, dict) or data.get('authenticated') is not True:
            raise ToolError('访问令牌无效或已过期，请重新执行 auth set-token。')
        return project(data, ('authenticated', 'user_id', 'username', 'is_admin', 'account_limit'))

    def accounts(self) -> list[dict]:
        data = self._request('GET', '/api/v1/cookies/options')
        if not isinstance(data, list):
            raise ToolError('账号列表格式不兼容。')
        return [project(row, ('id', 'enabled')) for row in data]

    def _page(self, path: str, fields: tuple[str, ...], account_id: str | None, page: int, page_size: int, **filters) -> dict:
        if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 100:
            raise ToolError('page 必须大于 0，page_size 必须在 1–100 之间。')
        params = {'page': page, 'page_size': page_size, **{k: v for k, v in filters.items() if v is not None}}
        if account_id is not None:
            params['cookie_id'] = identifier(account_id)
        data = self._request('GET', path, params=params)
        if not isinstance(data, dict) or not isinstance(data.get('data'), list):
            raise ToolError('分页结果格式不兼容。')
        return {**project(data, ('total', 'page', 'page_size', 'total_pages')), 'data': [project(row, fields) for row in data['data']]}

    def orders(self, account_id: str | None = None, page: int = 1, page_size: int = 20, status: str | None = None) -> dict:
        return self._page('/api/v1/orders', ('id', 'order_id', 'cookie_id', 'item_id', 'item_title', 'quantity', 'amount', 'status', 'created_at'), account_id, page, page_size, status=status)

    def items(self, account_id: str | None = None, page: int = 1, page_size: int = 20, keyword: str | None = None) -> dict:
        return self._page('/api/v1/items/paginated', ('id', 'item_id', 'account_id', 'cookie_id', 'title', 'item_title', 'price', 'item_price', 'item_quantity', 'item_status_desc', 'status'), account_id, page, page_size, keyword=keyword)

    def keywords(self, account_id: str) -> list[dict]:
        data = self._request('GET', f'/api/v1/keywords-with-item-id/{identifier(account_id)}')
        if not isinstance(data, list):
            raise ToolError('关键词列表格式不兼容。')
        return [project(row, ('id', 'keyword', 'reply', 'item_id', 'type', 'account_id')) for row in data]

    def set_account_enabled(self, account_id: str, enabled: bool, confirm: bool = False) -> dict:
        self._write(confirm)
        if type(enabled) is not bool:
            raise ToolError('enabled 必须是布尔值。')
        self._request('PUT', f'/api/v1/cookies/{identifier(account_id)}/status', body={'enabled': enabled})
        return {'success': True}

    def replace_keywords(self, account_id: str, keywords: list[dict], confirm: bool = False) -> dict:
        self._write(confirm)
        if not isinstance(keywords, list) or not 1 <= len(keywords) <= 100:
            raise ToolError('一次须提供 1–100 条文本关键词；不支持通过空列表清空。')
        payload = []
        for row in keywords:
            if not isinstance(row, dict) or set(row) - {'keyword', 'reply', 'item_id'}:
                raise ToolError('关键词仅支持 keyword、reply 和可选 item_id 字段。')
            for key, limit in [('keyword', 200), ('reply', 10000)]:
                if not isinstance(row.get(key), str) or not 1 <= len(row[key]) <= limit:
                    raise ToolError('关键词或回复文本为空或超长。')
            if row.get('item_id') is not None:
                identifier(row['item_id'])
            payload.append({**row, 'type': 'text'})
        # Upstream replaces every non-image rule, including external-contact rules.
        # Refuse rather than silently dropping rule kinds this client cannot preserve.
        existing = self.keywords(account_id)
        if any(str(row.get('type', 'text')).lower() not in ('text', 'image') for row in existing):
            raise ToolError('存在非文本/图片规则，请在 Web 后台编辑，避免替换时丢失特殊规则。')
        self._request('POST', f'/api/v1/keywords-with-item-id/{identifier(account_id)}', body={'keywords': payload})
        return {'success': True}

    def send_message(self, account_id: str, chat_id: str, to_user_id: str, message: str, confirm: bool = False) -> dict:
        self._write(confirm)
        for value, limit in [(chat_id, 200), (to_user_id, 80), (message, 10000)]:
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ToolError('消息参数为空或超长。')
        self._request('POST', '/api/v1/messages/send', body={'cookie_id': identifier(account_id), 'chat_id': chat_id, 'to_user_id': to_user_id, 'message': message})
        return {'success': True}
