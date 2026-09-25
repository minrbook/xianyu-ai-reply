"""JSON CLI. Secrets are read interactively or through explicit stdin, never argv."""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import sys

from .client import Client, ToolError, clear_credentials, normalize_url, save_credentials


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog='xianyu', description='闲鱼自托管服务 CLI；输出 JSON，默认只读。')
    root.add_argument('--url', help='服务根地址，必须与保存令牌的地址一致')
    commands = root.add_subparsers(dest='command', required=True)
    auth = commands.add_parser('auth').add_subparsers(dest='action', required=True)
    token = auth.add_parser('set-token', help='验证并保存已有访问令牌；不会绕过登录验证码')
    token.add_argument('--stdin', action='store_true', help='显式从标准输入读取令牌，供本地秘密管理器使用')
    auth.add_parser('clear', help='仅删除本地令牌，不撤销服务端令牌')
    for command in ('health', 'whoami', 'accounts'):
        commands.add_parser(command)
    for command in ('orders', 'items'):
        child = commands.add_parser(command)
        child.add_argument('--account-id')
        child.add_argument('--page', type=int, default=1)
        child.add_argument('--page-size', type=int, default=20)
        child.add_argument('--status' if command == 'orders' else '--keyword')
    keywords = commands.add_parser('keywords').add_subparsers(dest='action', required=True)
    child = keywords.add_parser('list')
    child.add_argument('account_id')
    child = keywords.add_parser('replace', help='替换指定账号的文本关键词集合，不是追加')
    child.add_argument('account_id')
    child.add_argument('--file', required=True, help='本地 JSON 数组文件；使用 - 从标准输入读取')
    child.add_argument('--confirm', action='store_true')
    child = commands.add_parser('account-status')
    child.add_argument('account_id')
    child.add_argument('state', choices=('enabled', 'disabled'))
    child.add_argument('--confirm', action='store_true')
    child = commands.add_parser('send', help='发送真实消息，内容从文件或标准输入读取')
    child.add_argument('account_id')
    child.add_argument('--chat-id', required=True)
    child.add_argument('--to-user-id', required=True)
    child.add_argument('--file', required=True, help='UTF-8 消息文件；使用 - 从标准输入读取')
    child.add_argument('--confirm', action='store_true')
    return root


def read_input(file: str) -> str:
    try:
        if file == '-':
            content = sys.stdin.read(2_000_001)
        else:
            with Path(file).open(encoding='utf-8') as stream:
                content = stream.read(2_000_001)
        if len(content) > 2_000_000:
            raise ToolError('输入文件过大。')
        return content
    except (OSError, UnicodeError):
        raise ToolError('无法读取 UTF-8 输入文件。') from None


def run(args) -> object:
    if args.command == 'auth':
        if args.action == 'clear':
            clear_credentials()
        else:
            url = normalize_url(args.url or os.environ.get('XIANYU_BASE_URL') or 'http://127.0.0.1:9000')
            if args.stdin:
                token = sys.stdin.read(16386).strip()
            else:
                if not sys.stdin.isatty():
                    raise ToolError('非交互环境请显式使用 --stdin，禁止把令牌放在命令参数中。')
                token = getpass.getpass('访问令牌（输入不回显）: ').strip()
            Client(url, token).whoami()
            save_credentials(url, token)
        return {'success': True}
    client = Client.from_environment(args.url)
    if args.command in ('health', 'whoami', 'accounts'):
        return getattr(client, args.command)()
    if args.command in ('orders', 'items'):
        options = {'account_id': args.account_id, 'page': args.page, 'page_size': args.page_size}
        options['status' if args.command == 'orders' else 'keyword'] = args.status if args.command == 'orders' else args.keyword
        return getattr(client, args.command)(**options)
    if args.command == 'keywords':
        if args.action == 'list':
            return client.keywords(args.account_id)
        client._write(args.confirm)
        try:
            keywords = json.loads(read_input(args.file))
        except ValueError:
            raise ToolError('关键词文件必须是 JSON 数组。') from None
        return client.replace_keywords(args.account_id, keywords, args.confirm)
    if args.command == 'account-status':
        return client.set_account_enabled(args.account_id, args.state == 'enabled', args.confirm)
    if args.command == 'send':
        client._write(args.confirm)
        return client.send_message(args.account_id, args.chat_id, args.to_user_id, read_input(args.file), args.confirm)
    raise ToolError('不支持的命令。')


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(parser().parse_args(argv))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except ToolError as exc:
        print(json.dumps({'success': False, 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print('{"success":false,"error":"操作取消"}', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
