"""WorkBuddy（copilot.tencent.com）每日签到：桌面端会话 accessToken + uid 直调。

协议源：GitHub Minatoxiaohu/agent-auto-signin workbuddy_signin.py（成长中心全家桶
中只取最小签到两接口）。响应契约：领取成功含 credit；已签=null/400 code10001。
凭证来源：PC 扫描 %LOCALAPPDATA%\\CodeBuddyExtension\\...\\workbuddy-desktop.info。
"""

from __future__ import annotations

from typing import Any

from app.http import http_json
from app.platforms import register
from app.platforms.base import Adapter, CheckinResult

WB_ENDPOINT = 'https://copilot.tencent.com'
WB_WEB_ENDPOINT = 'https://www.workbuddy.cn'
STATUS_PATH = '/v2/billing/meter/checkin-activity-status'
CLAIM_PATH = '/v2/billing/meter/daily-checkin'
SUMMARY_PATH = '/billing/meter/get-user-resource-summary'
PAID_PACKAGES_PATH = '/billing/meter/get-user-resource-paid-packages'
FREE_PACKAGES_PATH = '/billing/meter/get-user-resource-free-packages'

# 公开套餐码表（源 wb-switch credits.rs；多带不存在的码无副作用）
PAID_PACKAGE_CODES = [
    'TCACA_code_002_AkiJS3ZHF5', 'TCACA_code_023_4xbGhMrE6q',
    'TCACA_code_026_BaESVICNoi', 'TCACA_code_027_0FCGVA6vSa',
    'TCACA_code_009_0XmEQc2xOf', 'TCACA_code_038_OhvqZtiPKr',
    'TCACA_code_003_FAnt7lcmRT', 'TCACA_code_036_lupO5WgNdG',
]
FREE_PACKAGE_CODES = [
    'TCACA_code_008_cfWoLwvjU4', 'TCACA_code_007_nzdH5h4Nl0',
    'TCACA_code_028_NtpWi0jzXs', 'TCACA_code_029_6wCGEWquYy',
    'TCACA_code_030_BjSt89qTvr', 'TCACA_code_001_PqouKr6QWV',
    'TCACA_code_006_DbXS0lrypC', 'TCACA_code_035_ArVxJcGDsm',
    'TCACA_code_037_WxOD3MpI2o', 'TCACA_code_039_KRcQj7wUat',
    'TCACA_code_040_mi9rCYg46x',
]

# 商品码 → 官方前端文案（照抄 wb-switch credit-package-names.ts，
# 源官方客户端 package-name-resolver；未登记码回落 PackageName）
PACKAGE_NAMES = {
    'TCACA_code_001_PqouKr6QWV': 'CodeBuddy 个人体验版',
    'TCACA_code_002_AkiJS3ZHF5': '版本基础用量',
    'TCACA_code_003_FAnt7lcmRT': 'CodeBuddy 个人标准版',
    'TCACA_code_005_maRGyrHhw1': '版本基础用量',
    'TCACA_code_006_DbXS0lrypC': 'CodeBuddy 个人体验版',
    'TCACA_code_007_nzdH5h4Nl0': '平台奖励积分',
    'TCACA_code_008_cfWoLwvjU4': '版本基础用量',
    'TCACA_code_009_0XmEQc2xOf': '购买积分',
    'TCACA_code_023_4xbGhMrE6q': '版本基础用量',
    'TCACA_code_026_BaESVICNoi': '版本基础用量',
    'TCACA_code_027_0FCGVA6vSa': '版本基础用量',
    'TCACA_code_028_NtpWi0jzXs': '版本赠送用量',
    'TCACA_code_029_6wCGEWquYy': '平台奖励积分',
    'TCACA_code_030_BjSt89qTvr': '平台奖励积分',
    'TCACA_code_035_ArVxJcGDsm': '版本基础用量',
    'TCACA_code_036_lupO5WgNdG': '购买积分',
    'TCACA_code_037_WxOD3MpI2o': '版本赠送用量',
    'TCACA_code_038_OhvqZtiPKr': '购买积分',
    'TCACA_code_039_KRcQj7wUat': '版本基础用量',
    'TCACA_code_040_mi9rCYg46x': '版本基础用量',
}


def _dig(obj: Any, key: str) -> Any:
    """在可能被 data/result 包裹的响应里找字段（社区同款信封兼容）。"""
    if isinstance(obj, dict):
        if obj.get(key) is not None:
            return obj[key]
        for wrap in ('data', 'result'):
            inner = obj.get(wrap)
            if isinstance(inner, dict):
                val = _dig(inner, key)
                if val is not None:
                    return val
    return None


class WorkbuddyAdapter(Adapter):
    platform = 'workbuddy'
    title = 'WorkBuddy'
    credential_kind = 'token'

    def _headers(self, creds: dict[str, Any]) -> dict[str, str]:
        token = str(creds.get('token') or '').strip()
        if not token:
            from app.http import OpError
            raise OpError('缺少 accessToken', kind='auth')
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'X-User-Id': str(creds.get('uid') or ''),
            'User-Agent': 'WorkBuddy',
        }
        if creds.get('enterprise_id'):
            headers['X-Enterprise-Id'] = str(creds['enterprise_id'])
            headers['X-Tenant-Id'] = str(creds['enterprise_id'])
        if creds.get('domain'):
            headers['X-Domain'] = str(creds['domain'])
        return headers

    def _post(self, creds: dict[str, Any], path: str) -> Any:
        endpoint = str(creds.get('endpoint') or WB_ENDPOINT).rstrip('/')
        return http_json('POST', endpoint + path, self._headers(creds))

    def checkin(self, creds: dict[str, Any]) -> CheckinResult:
        st = self._post(creds, STATUS_PATH)
        if _dig(st, 'today_checked_in') in (True, 1):
            total = _dig(st, 'total_credits')
            today_credit = _dig(st, 'today_credit') or _dig(st, 'daily_credit')
            tail = f'（余 {total}）' if total else ''
            return CheckinResult(
                'already', f'今日已签到{tail}',
                f'+{today_credit} 积分' if today_credit else '')
        try:
            cl = self._post(creds, CLAIM_PATH)
        except Exception as exc:      # noqa: BLE001 —— 400 code10001 走"已签"判定
            from app.http import OpError
            text = str(exc)
            if '10001' in text or '已签到' in text:
                return CheckinResult('already', '今日已签到（服务端判定）')
            if isinstance(exc, OpError) and exc.kind == 'http':
                return CheckinResult('error', text[:120])
            if isinstance(exc, OpError) and exc.kind == 'parse' \
                    and text.rstrip().endswith('null'):
                return CheckinResult('already', '今日已签到（空响应幂等）')
            raise
        credit = _dig(cl, 'credit')
        if credit is not None:
            st2 = self._post(creds, STATUS_PATH)
            total = _dig(st2, 'total_credits') or _dig(st, 'total_credits')
            return CheckinResult('ok',
                                 f'WorkBuddy 签到成功 +{credit} 积分'
                                 + (f'（余 {total}）' if total else ''),
                                 f'+{credit} 积分')
        code = _dig(cl, 'code')
        msg = _dig(cl, 'msg') or _dig(cl, 'message') or ''
        return CheckinResult('error', f'领取失败 code={code} {msg}'
                             if code is not None or msg else
                             f'领取失败：响应缺少 credit {str(cl)[:100]}')

    def _web_summary(self, creds: dict[str, Any]) -> Any:
        # 官方余额在 www.workbuddy.cn 的资源 summary（copilot 域下 404）
        web = str(creds.get('web_endpoint') or WB_WEB_ENDPOINT).rstrip('/')
        headers = self._headers(creds)
        headers.update({'Origin': web, 'Referer': web + '/'})
        return http_json('POST', web + SUMMARY_PATH, headers)

    def credits(self, creds: dict[str, Any]) -> str | None:
        # = 各积分包 CycleRemainCapacity 之和（可为小数）
        total = 0.0
        for pack in (_dig(self._web_summary(creds), 'Packages') or []):
            if not isinstance(pack, dict):
                continue
            raw = (pack.get('CycleCapacityRemainPrecise')
                   or pack.get('CycleRemainCapacity')
                   or pack.get('CycleCapacityRemain') or 0)
            try:
                total += float(raw)
            except (TypeError, ValueError):
                continue
        if not total:
            return None
        return str(int(total)) if total == int(total) else str(round(total, 2))

    def breakdown(self, creds: dict[str, Any]) -> list[dict[str, str]]:
        # 逐包明细在 paid/free-packages 接口的 data.Accounts（含 DeductionEndTime），
        # 码表与到期解析移植自 wb-switch credits.rs（2026-09-23 实测）
        import time as _t
        from datetime import datetime
        from app.platforms.base import expire_text, fmt_amount
        web = str(creds.get('web_endpoint') or WB_WEB_ENDPOINT).rstrip('/')
        headers = self._headers(creds)
        headers.update({'Origin': web, 'Referer': web + '/'})
        now = _t.time()
        today = datetime.now()

        def _ts(value: Any) -> float | None:
            if value in (None, ''):
                return None
            try:
                num = float(value)
                return num / 1000 if num > 1e11 else num
            except (TypeError, ValueError):
                pass
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
                try:
                    return datetime.strptime(str(value)[:19], fmt).timestamp()
                except ValueError:
                    continue
            return None

        def _expire(a: dict) -> float | None:
            ded = _ts(a.get('DeductionEndTime') or a.get('ExpiredTime'))
            cyc = _ts(a.get('CycleEndTime'))
            val = ded if ded is not None else cyc
            if val is None:
                return None
            if ded is not None and cyc is not None and ded - cyc > 365 * 86400:
                val = cyc          # 2049 类长期占位 → 用周期结束时间
            return None if val > now + 730 * 86400 else val

        accounts: list[dict] = []
        for path, body in (
            (PAID_PACKAGES_PATH,
             {'PageNumber': 1, 'PageSize': 200, 'Status': [0, 3],
              'PackageCodes': PAID_PACKAGE_CODES, 'NeedRenewInfo': True}),
            (FREE_PACKAGES_PATH,
             {'PageNumber': 1, 'PageSize': 200, 'Status': [0, 3],
              'SlicePeriodStartTime': today.strftime('%Y-%m-%d 00:00:00'),
              'SlicePeriodEndTime': today.strftime('%Y-%m-%d 23:59:59'),
              'PackageCodes': FREE_PACKAGE_CODES}),
        ):
            try:
                resp = http_json('POST', web + path, headers, body=body)
            except Exception:               # noqa: BLE001 —— 一档失败不拖另一档
                continue
            accounts += [a for a in (_dig(resp, 'Accounts') or [])
                         if isinstance(a, dict)]
        stamped: list[tuple[float, dict[str, str]]] = []
        for a in accounts:
            raw = (a.get('CycleCapacityRemainPrecise')
                   or a.get('CycleCapacityRemain') or a.get('CapacityRemain'))
            try:
                remain = float(raw or 0)
            except (TypeError, ValueError):
                continue
            if remain <= 0:
                continue
            exp = _expire(a)
            code = str(a.get('PackageCode') or '')
            name = PACKAGE_NAMES.get(code) or str(
                a.get('PackageName') or code or '积分包')
            stamped.append((exp if exp is not None else float('inf'), {
                'tag': '资源包', 'name': name,
                'amount': fmt_amount(remain),
                'expire': expire_text(exp) if exp is not None else '长期有效'}))
        stamped.sort(key=lambda t: t[0])
        return [row for _, row in stamped]


register(WorkbuddyAdapter())
