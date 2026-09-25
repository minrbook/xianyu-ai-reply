#!/usr/bin/env python3
"""停机后加密旧凭据；只处理固定列，事务失败整批回滚，重复执行不会二次加密。"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import create_engine, inspect, text
from common.utils.credential_crypto import PREFIX, credential_cipher, encrypt_credential, decrypt_credential

COLUMNS = {
    "xy_accounts": ("cookie", "login_password"),
    "fy_accounts": ("cookie",),
    "xy_token_cache": ("token",),
}

def migrate(connection, *, verify_only=False):
    tables = set(inspect(connection).get_table_names())
    changed = 0
    for table, candidates in COLUMNS.items():
        if table not in tables:
            continue
        columns = {c["name"] for c in inspect(connection).get_columns(table)}
        fields = [c for c in candidates if c in columns]
        if table == "xy_accounts" and "metadata" in columns:
            fields.append("metadata")
        if not fields:
            continue
        last_id = -1
        while True:
            rows = connection.execute(text(f"SELECT id, {', '.join('`'+c+'`' for c in fields)} FROM `{table}` WHERE id > :last ORDER BY id LIMIT 500"), {"last": last_id}).mappings().all()
            if not rows:
                break
            for row in rows:
                last_id = row["id"]
                updates = {}
                for field in fields:
                    value = row[field]
                    if value is None or value == "":
                        continue
                    if field == "metadata":
                        meta = json.loads(value) if isinstance(value, str) else dict(value)
                        snapshot = meta.get("cookies_refresh_snapshot")
                        if snapshot is None:
                            continue
                        if isinstance(snapshot, str) and snapshot.startswith(PREFIX):
                            json.loads(decrypt_credential(snapshot))
                            continue
                        if verify_only:
                            raise RuntimeError("检测到旧版明文Cookie快照，请停机执行 scripts/migrate_credentials.py")
                        meta["cookies_refresh_snapshot"] = encrypt_credential(json.dumps(snapshot))
                        updates[field] = json.dumps(meta)
                    elif value.startswith(PREFIX):
                        decrypt_credential(value)
                    else:
                        if verify_only:
                            raise RuntimeError("检测到旧版明文凭据，请停机执行 scripts/migrate_credentials.py")
                        encoded = encrypt_credential(value)
                        if len(encoded.encode()) > 65535:
                            raise RuntimeError("加密后凭据超过TEXT容量，迁移已回滚")
                        updates[field] = encoded
                if updates:
                    statement = f"UPDATE `{table}` SET " + ', '.join(f"`{c}` = :{c}" for c in updates) + " WHERE id = :row_id"
                    connection.execute(text(statement), {**updates, "row_id": row["id"]})
                    changed += 1
    return changed

if __name__ == "__main__":
    from common.core.config import get_settings
    credential_cipher()
    engine = create_engine(get_settings().database_url, hide_parameters=True)
    with engine.begin() as conn:
        count = migrate(conn)
    print(f"凭据迁移完成：更新 {count} 行。密钥必须独立保管，旧明文备份不会被本脚本删除。")
