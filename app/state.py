"""每日签到状态（幂等基础）：state.json 原子写，损坏可恢复。"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from app.platforms.base import CheckinResult


class DailyState:
    def __init__(self, data_dir: Path):
        self._file = Path(data_dir) / 'state.json'

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
        data = self._load()
        data.setdefault(day, {})[platform] = {
            'state': result.state,
            'message': result.message,
            'reward': result.reward,
            'at': dt.datetime.now().strftime('%H:%M:%S'),
        }
        self._save(data)

    def done_today(self, platform: str) -> bool:
        today = dt.date.today().isoformat()
        rec = self.get(platform, today)
        return bool(rec) and rec.get('state') in ('ok', 'already')

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
