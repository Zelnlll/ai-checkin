"""凭证仓库：credentials/<platform>.json 持久化 + inbox 信箱导入 + 过期估算。"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

COOKIE_ASSUMED_VALID_DAYS = 30


class CredentialStore:
    def __init__(self, data_dir: Path, known_platforms: set[str]):
        self._root = Path(data_dir)
        self._cred_dir = self._root / 'credentials'
        self._inbox = self._root / 'inbox'
        self._known = known_platforms

    def _file(self, platform: str) -> Path:
        return self._cred_dir / f'{platform}.json'

    def load(self, platform: str) -> dict[str, Any] | None:
        try:
            data = json.loads(self._file(platform).read_text(encoding='utf-8'))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def save(self, platform: str, creds: dict[str, Any],
             saved_at: str | None = None) -> None:
        self._cred_dir.mkdir(parents=True, exist_ok=True)
        creds = dict(creds)
        creds['saved_at'] = saved_at or dt.datetime.now().isoformat(timespec='seconds')
        tmp = self._file(platform).with_suffix('.json.tmp')
        tmp.write_text(json.dumps(creds, ensure_ascii=False, indent=1), encoding='utf-8')
        tmp.replace(self._file(platform))

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
            existing = self.load(platform) or {}
            merged = {**existing, **{k: v for k, v in data.items() if k != 'saved_at'}}
            changed = any(existing.get(k) != merged.get(k)
                          for k in ('cookie', 'token', 'csrf'))
            self.save(platform, merged,
                      saved_at=existing.get('saved_at') if existing and not changed else None)
            path.replace(path.with_suffix('.json.imported'))  # 覆盖旧档，重复导入不炸
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
