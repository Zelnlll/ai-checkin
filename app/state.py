"""每日签到状态（幂等基础）：state.json 原子写，损坏可恢复。"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import time
from pathlib import Path
from typing import Any

from app.platforms.base import CheckinResult


class DailyState:
    def __init__(self, data_dir: Path):
        self._file = Path(data_dir) / 'state.json'

    @contextlib.contextmanager
    def _locked(self):
        """跨进程读改写锁（daemon/web 双容器共享卷）；10s 陈旧自动破锁。"""
        lock = self._file.with_suffix('.lock')
        lock.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + 5
        while True:
            try:
                os.mkdir(lock)
                break
            except FileExistsError:
                try:
                    if time.time() - lock.stat().st_mtime > 10:
                        os.rmdir(lock)
                        continue
                except OSError:
                    pass
                if time.time() > deadline:
                    break          # 拿不到锁也要工作：宁可冒竞态不冒停摆
                time.sleep(0.05)
        try:
            yield
        finally:
            try:
                os.rmdir(lock)
            except OSError:
                pass

    def _load(self) -> dict[str, dict[str, dict[str, Any]]]:
        try:
            raw = json.loads(self._file.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                return {d: v for d, v in raw.items() if isinstance(v, dict)}
        except Exception:
            pass
        return {}

    def _save(self, data: dict) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._file.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
        tmp.replace(self._file)

    def get(self, platform: str, day: str) -> dict[str, Any] | None:
        return self._load().get(day, {}).get(platform)

    def mark(self, platform: str, result: CheckinResult, day: str) -> None:
        with self._locked():
            data = self._load()
            rec = data.setdefault(day, {}).setdefault(platform, {})
            rec.update({
                'state': result.state,
                'message': result.message,
                'reward': result.reward,
                'balance': result.balance,
                'streak': result.streak,
                'at': dt.datetime.now().strftime('%H:%M:%S'),
            })
            self._save(data)

    def done_today(self, platform: str) -> bool:
        today = dt.date.today().isoformat()
        rec = self.get(platform, today)
        return bool(rec) and rec.get('state') in ('ok', 'already')

    def touch_keepalive(self, platform: str, day: str) -> None:
        with self._locked():
            data = self._load()
            rec = data.setdefault(day, {}).setdefault(platform, {})
            rec['keepalive'] = day
            self._save(data)

    def streak(self, platform: str, day: str) -> int:
        """连续签到天数：day 当天未签则从昨天往前数。"""
        data = self._load()

        def done(d: str) -> bool:
            rec = data.get(d, {}).get(platform)
            return bool(rec) and rec.get('state') in ('ok', 'already')

        cursor = dt.date.fromisoformat(day)
        if not done(cursor.isoformat()):
            cursor -= dt.timedelta(days=1)
        count = 0
        while done(cursor.isoformat()):
            count += 1
            cursor -= dt.timedelta(days=1)
        return count
