"""Qoder（openapi.qoder.com.cn）：campaigns 活动领取通道。

红线（qoder2api 权威结论）：legacy daily-check-in/claim 已 DISABLED 恒返 409，
绝不请求该端点；409 一律按失败处理，不当"已签到"。
"""

from __future__ import annotations

from typing import Any

from app.http import OpError, http_json, jwt_exp_s
from app.platforms import register
from app.platforms.base import Adapter, CheckinResult

QODER_OPENAPI = 'https://openapi.qoder.com.cn'


def _headers(token: str, *, origin: bool = False) -> dict[str, str]:
    headers = {
        'Authorization': f'Bearer {token}',
        'cosy-clienttype': '10',
        'user-agent': 'Qoder',
        'accept': 'application/json',
    }
    if origin:
        headers['origin'] = QODER_OPENAPI
    return headers


class QoderAdapter(Adapter):
    platform = 'qoder'
    title = 'Qoder'
    credential_kind = 'token'

    def checkin(self, creds: dict[str, Any]) -> CheckinResult:
        token = str(creds.get('token') or '').strip()
        if token.lower().startswith('bearer '):
            token = token[7:].strip()
        if not token:
            raise OpError('缺少 token（抓包 openapi.qoder.com.cn 请求头复制）', kind='auth')
        data = http_json('GET', f'{QODER_OPENAPI}/sash/api/v1/me/campaigns',
                         _headers(token))
        campaigns = data.get('campaigns') if isinstance(data, dict) else None
        campaigns = [c for c in campaigns or [] if isinstance(c, dict)]
        claimable = [c for c in campaigns
                     if c.get('actionType') == 'CLAIM_BENEFIT'
                     and c.get('claimStatus') == 'CLAIMABLE']
        parts, amounts, had_error = [], [], False
        for campaign in claimable:
            cid = campaign.get('campaignId')
            if cid is None:
                continue
            try:
                result = http_json('POST',
                                   f'{QODER_OPENAPI}/sash/api/v1/me/campaigns/{cid}/claim',
                                   _headers(token, origin=True))
            except OpError as exc:
                if exc.kind == 'auth':
                    raise
                had_error = True
                parts.append(f'活动[{cid}]领取失败：{exc}')
                continue
            amount = None
            if isinstance(result, dict):
                benefit = result.get('benefit')
                amount = benefit.get('amount') if isinstance(benefit, dict) \
                    else result.get('amount')
            if amount is not None:
                amounts.append(int(amount))
            parts.append(f"活动[{campaign.get('campaignKey') or cid}] 领取成功"
                         + (f' +{amount}' if amount is not None else ''))
        if amounts:
            total = sum(amounts)
            return CheckinResult('ok', '；'.join(parts), f'+{total} Credits')
        if had_error:
            return CheckinResult('error', '；'.join(parts))
        if any(c.get('actionType') == 'CLAIM_BENEFIT' and c.get('claimStatus') == 'CLAIMED'
               for c in campaigns):
            return CheckinResult('already', '今日活动已领取')
        return CheckinResult('error', '当前无可领活动（每日 10:00 开放）')

    def token_status(self, creds: dict[str, Any]) -> dict[str, Any]:
        import datetime as dt
        import time
        exp = jwt_exp_s(str(creds.get('token') or '').removeprefix('Bearer ').strip())
        if not exp:
            return {'known': False, 'expired': False, 'expires_at': '', 'days_left': None}
        left = exp - time.time()
        return {'known': True, 'expired': left <= 0,
                'expires_at': dt.datetime.fromtimestamp(exp).strftime('%Y-%m-%d %H:%M'),
                'days_left': round(left / 86400, 1)}


register(QoderAdapter())
