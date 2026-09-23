"""凭证仓库：credentials/<platform>.json 持久化 + inbox 信箱导入 + 过期估算。

文件格式：{"accounts": [ {凭证字段…, "id": "main"|短哈希, "label"?: 名字 } ]}。
旧扁平文件（单账号 dict）读时视为 id=main 的唯一账号。
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

COOKIE_ASSUMED_VALID_DAYS = 30

_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,16}$')


def _acct_id(creds: dict[str, Any]) -> str:
    raw = str(creds.get('token') or creds.get('cookie') or '')
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:8]


def sanitize_acct_id(acct_id: Any) -> str | None:
    """账号 id 白名单：非法输入（可能来自网页表单注入）一律丢弃重派。"""
    s = str(acct_id or '')
    return s if _ID_RE.match(s) else None


def sanitize_label(label: Any) -> str:
    s = re.sub(r'[<>"\'&\r\n\t]', '', str(label or ''))
    return s[:20]


class CredentialStore:
    def __init__(self, data_dir: Path, known_platforms: set[str]):
        self._root = Path(data_dir)
        self._cred_dir = self._root / 'credentials'
        self._inbox = self._root / 'inbox'
        self._known = known_platforms

    def _file(self, platform: str) -> Path:
        return self._cred_dir / f'{platform}.json'

    def load_all(self, platform: str) -> list[dict[str, Any]]:
        try:
            data = json.loads(self._file(platform).read_text(encoding='utf-8'))
        except Exception:
            return []
        if not isinstance(data, dict):
            return []
        if 'accounts' in data:
            return [a for a in data['accounts'] if isinstance(a, dict)]
        return [{**data, 'id': 'main'}]          # 旧扁平格式

    def load(self, platform: str) -> dict[str, Any] | None:
        accounts = self.load_all(platform)
        return accounts[0] if accounts else None

    @contextlib.contextmanager
    def _locked(self):
        """凭证目录跨进程锁；未持锁不许 rmdir，避免偷删别人的锁。"""
        self._cred_dir.mkdir(parents=True, exist_ok=True)
        lock = self._cred_dir / '.lock'
        deadline = time.time() + 5
        held = False
        while True:
            try:
                os.mkdir(lock)
                held = True
                break
            except FileExistsError:
                try:
                    if time.time() - lock.stat().st_mtime > 10:
                        os.rmdir(lock)
                        continue
                except OSError:
                    pass
                if time.time() > deadline:
                    break          # 拿不到锁也工作：宁可冒竞态不冒停摆
                time.sleep(0.05)
        try:
            yield
        finally:
            if held:
                try:
                    os.rmdir(lock)
                except OSError:
                    pass

    def _write(self, platform: str, accounts: list[dict[str, Any]]) -> None:
        target = self._file(platform)
        tmp = target.with_name(f'{target.name}.{os.getpid()}.tmp')
        tmp.write_text(json.dumps({'accounts': accounts}, ensure_ascii=False,
                                  indent=1), encoding='utf-8')
        tmp.replace(target)

    def _save_accounts(self, platform: str, accounts: list[dict[str, Any]]) -> None:
        with self._locked():
            self._write(platform, accounts)

    def save(self, platform: str, creds: dict[str, Any],
             saved_at: str | None = None) -> None:
        creds = dict(creds)
        creds['saved_at'] = saved_at or dt.datetime.now().isoformat(timespec='seconds')
        creds['id'] = creds.get('id') or 'main'
        self._save_accounts(platform, [creds])

    def upsert(self, platform: str, creds: dict[str, Any],
               acct_id: str | None = None,
               rotate_single: bool = False) -> None:
        """更新或追加账号：显式 id > 主凭证相同 > 新增。读改写全程持锁。

        rotate_single=True（inbox 导入用）：仅有一个账号且不匹配时视为该账号
        凭证轮换并合并——PC 端扫描/登录工具导出的永远是本机那一个账号。
        """
        new = dict(creds)
        acct_id = sanitize_acct_id(acct_id)
        if 'label' in new:
            new['label'] = sanitize_label(new['label'])
        now = dt.datetime.now().isoformat(timespec='seconds')
        primary = new.get('token') or new.get('cookie')
        with self._locked():
            accounts = self.load_all(platform)

            def _merge(target: dict[str, Any]) -> None:
                changed = any(target.get(k) != new.get(k)
                              for k in ('cookie', 'token', 'csrf'))
                target.update({k: v for k, v in new.items() if k != 'saved_at'})
                target['saved_at'] = target.get('saved_at') if not changed else now
                target.setdefault('saved_at', now)

            target = None
            if acct_id:
                target = next((a for a in accounts if a.get('id') == acct_id), None)
            elif primary:
                target = next((a for a in accounts
                               if (a.get('token') or a.get('cookie')) == primary), None)
                if target is None and rotate_single and len(accounts) == 1:
                    target = accounts[0]  # 单账号 token 刷新不建重复号
            if target is None:
                if acct_id:
                    new['id'] = acct_id       # 显式指定 id：按其建号
                elif not accounts:
                    new['id'] = 'main'        # 空仓库首账号：main，state 旧键零迁移
                else:
                    new.setdefault('id', _acct_id(new) if primary
                                   else f'a{len(accounts) + 1}')
                new.setdefault('saved_at', now)
                accounts.append(new)
            else:
                _merge(target)
            self._write(platform, accounts)

    def remove(self, platform: str, acct_id: str | None = None) -> None:
        if not acct_id:
            self.clear(platform)
            return
        with self._locked():
            accounts = [a for a in self.load_all(platform)
                        if a.get('id') != acct_id]
            if accounts:
                self._write(platform, accounts)
                return
        self.clear(platform)

    def clear(self, platform: str) -> dict[str, Any]:
        for p in (self._file(platform),
                  self._inbox / f'{platform}.json',
                  self._inbox / f'{platform}.json.imported'):
            try:
                p.unlink()
            except OSError:
                pass
        return {'cleared': True, 'message': f'{platform} 凭证已清空'}

    def import_inbox(self) -> list[tuple[str, str]]:
        """扫描 inbox/<platform>.json，合法则导入并把源文件改名为 .imported。"""
        imported: list[tuple[str, str]] = []
        if not self._inbox.is_dir():
            return imported
        for path in sorted(self._inbox.glob('*.json')):
            platform = path.stem
            if platform not in self._known:
                continue
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
            except Exception:
                continue
            if not isinstance(data, dict) or not (data.get('cookie') or data.get('token')):
                continue
            self.upsert(platform, data, rotate_single=True)
            try:
                path.replace(path.with_suffix('.json.imported'))  # 并发双导入幂等
            except FileNotFoundError:
                pass
            imported.append((platform, path.name))
        return imported

    def expiry_report(self, platform: str, creds: dict[str, Any],
                      adapter: Any) -> dict[str, Any]:
        status = dict(adapter.token_status(creds))
        if not status.get('known') and adapter.credential_kind == 'cookie':
            saved_at = str(creds.get('saved_at') or '')
            try:
                saved = dt.datetime.fromisoformat(saved_at)
                age_days = (dt.datetime.now() - saved).days
            except ValueError:
                age_days = 0
            status['likely_expired_soon'] = age_days >= COOKIE_ASSUMED_VALID_DAYS * 0.8
        else:
            status['likely_expired_soon'] = bool(status.get('expired'))
        return status
