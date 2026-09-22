"""企业微信自建应用通道：gettoken 缓存 + message/send markdown。

目标二选一：WECOM_CHAT_ID（应用会话群）优先，否则 WECOM_TO_USER（成员 userid）。
access_token 缓存于 DATA_DIR/wecom_app_token.json，失效（40001/42001）自动重取并重试一次。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import time
from typing import Any, Callable

import urllib.request
from app.http import http_json
from app.notify import build_markdown
from app.report_html import build_report_html
from app.scheduler import CheckinOutcome

logger = logging.getLogger(__name__)
API_BASE = 'https://qyapi.weixin.qq.com/cgi-bin'

_TOKEN_INVALID_CODES = (40001, 40002, 42001)


class WeComAppNotifier:
    def __init__(self, cfg, get: Callable[..., Any] = http_json,
                 post: Callable[..., Any] = http_json,
                 render: Callable[[str], bytes] | None = None,
                 upload: Callable[[str, str, bytes], str] | None = None):
        self._cfg = cfg
        self._base = getattr(cfg, 'wecom_api_base', '') or API_BASE
        self._render = render
        self._upload = upload
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
        self._cache_file.write_text(json.dumps(
            {'access_token': token, 'expires_at': expires_at}), encoding='utf-8')
        return token

    def _send(self, token: str, payload: dict) -> dict:
        url = f'{self._base}/message/send?access_token={token}'
        return self._post('POST', url, {}, body=payload)

    def _target_fields(self) -> dict[str, Any]:
        cfg = self._cfg
        if cfg.wecom_chat_id:
            return {'chatid': cfg.wecom_chat_id}
        return {'touser': cfg.wecom_to_user}

    def _send(self, token: str, payload: dict) -> dict:
        url = f'{self._base}/message/send?access_token={token}'
        return self._post('POST', url, {}, body=payload)

    def _send_with_retry(self, payload: dict) -> bool:
        token = self._token()
        if not token:
            return False
        try:
            resp = self._send(token, payload)
        except Exception as exc:
            logger.error('企微应用推送异常：%s', exc)
            return False
        if isinstance(resp, dict) and resp.get('errcode') in _TOKEN_INVALID_CODES:
            token = self._token(force_refresh=True)
            if not token:
                return False
            try:
                resp = self._send(token, payload)
            except Exception as exc:
                logger.error('企微应用推送重试异常：%s', exc)
                return False
        if not isinstance(resp, dict) or resp.get('errcode') != 0:
            logger.error('企微应用推送被拒：%s', resp)
            return False
        return True

    def _push_image(self, outcomes, today: str) -> bool:
        render = self._render
        if render is None:
            from app.report_render import render_png as render  # noqa: F811
        upload = self._upload or upload_media
        png = render(build_report_html(outcomes, today))
        token = self._token()
        if not token:
            return False
        media_id = upload(self._base, token, png)
        payload: dict[str, Any] = {
            'agentid': self._cfg.wecom_agent_id,
            'msgtype': 'image', 'image': {'media_id': media_id},
            **self._target_fields(),
        }
        return self._send_with_retry(payload)

    def push(self, outcomes: list[CheckinOutcome], today: str) -> bool:
        cfg = self._cfg
        if not (cfg.wecom_corp_id and cfg.wecom_corp_secret and cfg.wecom_agent_id):
            logger.warning('企微应用通道未配置（corpid/secret/agentid），跳过推送')
            return False
        if not (cfg.wecom_chat_id or cfg.wecom_to_user):
            logger.warning('企微应用通道缺少接收目标（WECOM_CHAT_ID 或 WECOM_TO_USER）')
            return False
        try:
            if self._push_image(outcomes, today):
                return True
            logger.warning('图片通知失败，回退 markdown')
        except Exception as exc:
            logger.warning('图片通知异常（%s），回退 markdown', exc)
        payload: dict[str, Any] = {
            'agentid': cfg.wecom_agent_id,
            **build_markdown(outcomes, today),
            **self._target_fields(),
        }
        return self._send_with_retry(payload)


def upload_media(base: str, token: str, png: bytes) -> str:
    """企微临时素材上传（multipart），返回 media_id。"""
    boundary = '----aiCheckInReportBoundary'
    crlf = bytes([13, 10])
    head = (f'--{boundary}'.encode('utf-8') + crlf
            + b'Content-Disposition: form-data; name="media"; filename="report.png"' + crlf
            + b'Content-Type: image/png' + crlf + crlf)
    tail = crlf + f'--{boundary}--'.encode('utf-8') + crlf
    body = head + png + tail
    url = f'{base}/media/upload?access_token={token}&type=image'
    req = urllib.request.Request(
        url, data=body,
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        import json as _json
        data = _json.loads(resp.read().decode('utf-8', 'replace'))
    if data.get('errcode') not in (0, None) or 'media_id' not in data:
        raise RuntimeError(f'media 上传失败：{data}')
    return str(data['media_id'])


def make_notifier(cfg):
    """按配置选通道：应用（corpid 齐全）优先，其次群机器人 webhook。"""
    if cfg.wecom_corp_id and cfg.wecom_corp_secret and cfg.wecom_agent_id:
        return WeComAppNotifier(cfg)
    from app.notify import WeComNotifier
    return WeComNotifier(cfg.wecom_webhook)
