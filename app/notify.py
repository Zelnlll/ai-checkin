"""企业微信群机器人通知（纯文本兜底格式）；推送失败绝不影响签到主流程。"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Callable

from app.http import http_json
from app.platforms import get_adapter
from app.scheduler import CheckinOutcome

logger = logging.getLogger(__name__)

# 通知行首统一同款菱形：全平台 🔸 小橙菱，失败 🔻 红色警示
_DOT = '🔸'


def _dot(o: CheckinOutcome) -> str:
    return '🔻' if o.result.state == 'error' else _DOT


_SHORT_TITLES = {'MiniMax Code': 'MiniMax'}


def _compact(text: str) -> str:
    for word in (' 积分', ' 魔粒', '积分', '魔粒'):
        text = text.replace(word, '')
    return text.replace(' Credits', '').replace('Credits', '').replace('Cr', '').strip()


def _title(o: CheckinOutcome) -> str:
    try:
        return get_adapter(o.platform).title
    except KeyError:
        return o.platform


def build_text(outcomes: list[CheckinOutcome], today: str) -> dict[str, Any]:
    """纯文本兜底：微信插件保证可见，无任何标签。"""
    failed = [o for o in outcomes if o.result.state == 'error']
    done = sum(1 for o in outcomes if o.result.done())
    head = (f'每日签到 {today} · '
            + (f'有失败 {done}/{len(outcomes)}' if failed else f'签到成功 {done}/{len(outcomes)}'))
    lines = [head]
    for o in outcomes:
        detail = (o.result.message if o.result.state == 'error'
                  else o.result.reward or o.result.message)
        lines.append(f'{_dot(o)} {_title(o)} {detail}'[:60])
    return {'msgtype': 'text', 'text': {'content': chr(10).join(lines)}}


def build_textcard(outcomes: list[CheckinOutcome], today: str) -> dict[str, Any]:
    """textcard=微信插件支持的大标题+小字明细；行1 🔸平台+积分，行2 到期/余/连。"""
    failed = [o for o in outcomes if o.result.state == 'error']
    done = sum(1 for o in outcomes if o.result.done())
    n = len(outcomes)
    head = f'签到成功 {done}/{n}' if not failed else f'有失败 {done}/{n}'
    lines = [today]
    for o in outcomes:
        r = o.result
        detail = (r.message if r.state == 'error'
                  else r.reward or (r.message if r.state == 'busy' else '已签到'))
        detail = _compact(detail)
        name = _SHORT_TITLES.get(_title(o), _title(o))
        extras = []
        if r.expiring:
            extras.append(r.expiring.replace(' · ', '·'))
        if r.balance:
            extras.append(f'余{r.balance}')
        if r.streak >= 2:
            extras.append(f'连{r.streak}天')
        lines.append(f'{_dot(o)} {name} {detail}'[:40])
        if extras:
            lines.append('　' + '｜'.join(extras))
    while len(chr(10).join(lines).encode('utf-8')) > 500 and len(lines) > 2:
        if lines[-1].startswith('　'):
            lines.pop()
        lines.pop()          # 超字节从尾部整块（平台行+明细行）删起
    desc = chr(10).join(lines)
    return {'msgtype': 'textcard', 'textcard': {
        'title': head,
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
