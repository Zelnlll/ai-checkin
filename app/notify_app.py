"""企业微信自建应用通道：gettoken 缓存 + message/send textcard（大标题+小字明细）。

主格式 textcard 在微信插件原生渲染（粗大标题+灰色小字+绿色高亮）；
被拒时兜底纯 text（微信插件保证可见）。markdown 在微信插件显示"不支持"，禁用。
目标二选一：WECOM_CHAT_ID 优先，否则 WECOM_TO_USER。
access_token 缓存于 DATA_DIR/wecom_app_token.json，失效（40001/42001）自动重取并重试一次。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from app.http import http_json
from app.notify import build_text, build_textcard
from app.scheduler import CheckinOutcome

logger = logging.getLogger(__name__)
API_BASE = 'https://qyapi.weixin.qq.com/cgi-bin'

_TOKEN_INVALID_CODES = (40001, 40002, 42001)


class WeComAppNotifier:
    def __init__(self, cfg, get: Callable[..., Any] = http_json,
                 post: Callable[..., Any] = http_json):
        self._cfg = cfg
        self._base = getattr(cfg, 'wecom_api_base', '') or API_BASE
        self._get = get
        self._post = post
        self._cache_file = cfg.data_dir / 'wecom_app_token.json'

    def _token(self, force_refresh: bool = False) -> str | None:
        if not force_refresh and self._cache_file.exists():
            try:
                cached = json.loads(self._cache_file.read_text(encoding='utf-8'))
                if cached.get('expires_at', 0) > time.time():
                    return str(cached['access_token'])
            except Exception:
                pass
        if not (self._cfg.wecom_corp_id and self._cfg.wecom_corp_secret):
            return None
        url = (f'{self._base}/gettoken?corpid={self._cfg.wecom_corp_id}'
               f'&corpsecret={self._cfg.wecom_corp_secret}')
        try:
            resp = self._get('GET', url, {})
        except Exception as exc:
            logger.error('企微 gettoken 异常：%s', exc)
            return None
        if not isinstance(resp, dict) or resp.get('errcode') != 0:
            logger.error('企微 gettoken 失败：%s', resp)
            return None
        token = str(resp['access_token'])
        expires_at = time.time() + int(resp.get('expires_in') or 7200) - 300
        self._cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._cache_file.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(
            {'access_token': token, 'expires_at': expires_at}), encoding='utf-8')
        tmp.replace(self._cache_file)
        return token

    def _target_fields(self) -> dict[str, Any]:
        cfg = self._cfg
        if cfg.wecom_chat_id:
            return {'chatid': cfg.wecom_chat_id}
        return {'touser': cfg.wecom_to_user}

    def _send(self, token: str, payload: dict) -> dict:
        url = f'{self._base}/message/send?access_token={token}'
        return self._post('POST', url, {}, body=payload)

    def _send_with_retry(self, payload: dict) -> dict | None:
        """返回响应 dict（errcode!=0 时已含），token 失效自动重取重试一次。"""
        token = self._token()
        if not token:
            return None
        try:
            resp = self._send(token, payload)
        except Exception as exc:
            logger.error('企微应用推送异常：%s', exc)
            return None
        if isinstance(resp, dict) and resp.get('errcode') in _TOKEN_INVALID_CODES:
            token = self._token(force_refresh=True)
            if not token:
                return None
            try:
                resp = self._send(token, payload)
            except Exception as exc:
                logger.error('企微应用推送重试异常：%s', exc)
                return None
        return resp

    @staticmethod
    def _ok(resp: dict | None) -> bool:
        return isinstance(resp, dict) and resp.get('errcode') == 0

    def push(self, outcomes: list[CheckinOutcome], today: str) -> bool:
        cfg = self._cfg
        if not (cfg.wecom_corp_id and cfg.wecom_corp_secret and cfg.wecom_agent_id):
            logger.warning('企微应用通道未配置（corpid/secret/agentid），跳过推送')
            return False
        if not (cfg.wecom_chat_id or cfg.wecom_to_user):
            logger.warning('企微应用通道缺少接收目标（WECOM_CHAT_ID 或 WECOM_TO_USER）')
            return False
        payload: dict[str, Any] = {
            'agentid': cfg.wecom_agent_id,
            **build_textcard(outcomes, today),
            **self._target_fields(),
        }
        resp = self._send_with_retry(payload)
        if self._ok(resp):
            return True
        logger.warning('textcard 推送失败（%s），兜底纯文本', resp)
        fallback: dict[str, Any] = {
            'agentid': cfg.wecom_agent_id,
            **build_text(outcomes, today),
            **self._target_fields(),
        }
        resp = self._send_with_retry(fallback)
        if not self._ok(resp):
            logger.error('企微应用推送被拒：%s', resp)
            return False
        return True


def make_notifier(cfg):
    """按配置选通道：应用（corpid 齐全）优先，其次群机器人 webhook。"""
    if cfg.wecom_corp_id and cfg.wecom_corp_secret and cfg.wecom_agent_id:
        return WeComAppNotifier(cfg)
    from app.notify import WeComNotifier
    return WeComNotifier(cfg.wecom_webhook)
