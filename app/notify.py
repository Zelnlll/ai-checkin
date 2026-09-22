"""企业微信群机器人通知（纯文本兜底格式）；推送失败绝不影响签到主流程。"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Callable

from app.http import http_json
from app.platforms import get_adapter
from app.scheduler import CheckinOutcome

logger = logging.getLogger(__name__)

_STATE_ICON = {'ok': '✅', 'already': '✔', 'busy': '⏳', 'error': '❌'}


def _title(o: CheckinOutcome) -> str:
    try:
        return get_adapter(o.platform).title
    except KeyError:
        return o.platform


def build_text(outcomes: list[CheckinOutcome], today: str) -> dict[str, Any]:
    """纯文本兜底：微信插件保证可见，无任何标签。"""
    failed = [o for o in outcomes if o.result.state == 'error']
    done = sum(1 for o in outcomes if o.result.done())
    head = (f'📋 每日签到 {today} · '
            + (f'有失败 {done}/{len(outcomes)}' if failed else f'全部成功 {done}/{len(outcomes)}'))
    lines = [head]
    for o in outcomes:
        icon = _STATE_ICON.get(o.result.state, '❓')
        detail = o.result.reward or o.result.message
        lines.append(f'{icon} {_title(o)} {detail}'[:60])
    return {'msgtype': 'text', 'text': {'content': chr(10).join(lines)}}


def build_textcard(outcomes: list[CheckinOutcome], today: str) -> dict[str, Any]:
    """textcard=微信插件支持的大标题+小字明细格式，奖励绿色高亮。"""
    failed = [o for o in outcomes if o.result.state == 'error']
    done = sum(1 for o in outcomes if o.result.done())
    n = len(outcomes)
    head = f'全部成功 {done}/{n}' if not failed else f'有失败 {done}/{n}'
    lines = [today]
    for o in outcomes:
        icon = _STATE_ICON.get(o.result.state, '❓')
        r = o.result
        detail = r.reward or (r.message if r.state == 'error' else '已签到')
        lines.append(f'{icon} {_title(o)} {detail}'[:40])
    rows = lines[:]
    while len(chr(10).join(rows).encode('utf-8')) > 500 and len(rows) > 2:
        rows.pop()
    desc = chr(10).join(rows)
    return {'msgtype': 'textcard', 'textcard': {
        'title': f'📋 {head}',
        'description': desc,
        'url': 'https://work.weixin.qq.com',
    }}


class WeComNotifier:
    def __init__(self, webhook: str,
                 post: Callable[..., Any] = http_json):
        self._webhook = webhook
        self._post = post

    def push(self, outcomes: list[CheckinOutcome], today: str) -> bool:
        if not self._webhook:
            logger.warning('WECOM_WEBHOOK 未配置，跳过推送')
            return False
        payload = build_text(outcomes, today)
        try:
            resp = self._post('POST', self._webhook, {}, body=payload)
        except Exception as exc:
            logger.error('企微推送异常：%s', exc)
            return False
        if not isinstance(resp, dict) or resp.get('errcode') != 0:
            logger.error('企微推送被拒：%s', resp)
            return False
        return True
