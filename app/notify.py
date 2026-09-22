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


def _row_value(outcome: CheckinOutcome) -> str:
    r = outcome.result
    icon = _STATE_ICON.get(r.state, '❓')
    if r.state == 'ok':
        return f'{icon} 成功 {r.reward or r.message}'.strip()
    if r.state == 'already':
        return f'{icon} 已签到 {r.reward}'.strip()
    return f'{icon} 失败：{r.message}'


def build_card(outcomes: list[CheckinOutcome], today: str) -> dict[str, Any]:
    failed = [o for o in outcomes if o.result.state == 'error']
    rows = []
    for o in outcomes:
        try:
            title = get_adapter(o.platform).title
        except KeyError:
            title = o.platform
        rows.append({'keyname': title, 'value': _row_value(o)})
    return {'template_card': {
        'card_type': 'text_notice',
        'main_title': {'title': '每日签到 · 有失败' if failed else '每日签到 · 全部成功'},
        'sub_title_text': today,
        'horizontal_content_list': rows,
        'card_action': {'type': 1, 'url': 'https://qyapi.weixin.qq.com'},
        **({'emphasis_indicator': 1} if failed else {}),
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
        payload = {'msgtype': 'template_card', **build_card(outcomes, today)}
        try:
            resp = self._post('POST', self._webhook, {}, body=payload)
        except Exception as exc:
            logger.error('企微推送异常：%s', exc)
            return False
        if not isinstance(resp, dict) or resp.get('errcode') != 0:
            logger.error('企微推送被拒：%s', resp)
            return False
        return True
