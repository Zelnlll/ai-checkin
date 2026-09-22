"""企业微信群机器人通知：text_notice 汇总卡片，推送失败绝不影响签到主流程。"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Callable

from app.http import http_json
from app.platforms import get_adapter
from app.scheduler import CheckinOutcome

logger = logging.getLogger(__name__)

_STATE_ICON = {'ok': '✅', 'already': '✔', 'busy': '⏳', 'error': '❌'}


def _row_title(outcome: CheckinOutcome) -> str:
    try:
        title = get_adapter(outcome.platform).title
    except KeyError:
        title = outcome.platform
    icon = _STATE_ICON.get(outcome.result.state, '❓')
    return f'{icon} **{title}**'


def _row_desc(outcome: CheckinOutcome) -> str:
    r = outcome.result
    if r.state == 'error':
        return f'<font color="warning">{r.message[:60]}</font>'
    if r.state == 'busy':
        return f'<font color="comment">{r.message[:60]}</font>'
    return r.reward or r.message[:60]


def build_markdown(outcomes: list[CheckinOutcome], today: str) -> dict[str, Any]:
    failed = [o for o in outcomes if o.result.state == 'error']
    done_count = sum(1 for o in outcomes if o.result.done())
    n = len(outcomes)
    if failed:
        head = f'**{today} · <font color="warning">有失败 {done_count}/{n}</font>**'
    else:
        head = f'**{today} · <font color="info">全部成功 {done_count}/{n}</font>**'
    lines = ['# 📋 AI 平台签到', head, '']
    rewards = [o.result.reward for o in outcomes if o.result.reward]
    if rewards:
        lines.append(f'> 战利品：{" · ".join(rewards)}')
        lines.append('')
    for o in outcomes:
        lines.append(f'{_row_title(o)}　{_row_desc(o)}')
    return {'msgtype': 'markdown', 'markdown': {'content': chr(10).join(lines)}}


class WeComNotifier:
    def __init__(self, webhook: str,
                 post: Callable[..., Any] = http_json):
        self._webhook = webhook
        self._post = post

    def push(self, outcomes: list[CheckinOutcome], today: str) -> bool:
        if not self._webhook:
            logger.warning('WECOM_WEBHOOK 未配置，跳过推送')
            return False
        payload = build_markdown(outcomes, today)
        try:
            resp = self._post('POST', self._webhook, {}, body=payload)
        except Exception as exc:
            logger.error('企微推送异常：%s', exc)
            return False
        if not isinstance(resp, dict) or resp.get('errcode') != 0:
            logger.error('企微推送被拒：%s', resp)
            return False
        return True
