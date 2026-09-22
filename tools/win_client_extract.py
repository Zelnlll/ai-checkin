"""Windows PC 端凭证提取：从桌面客户端本地存储导入可用凭证到 inbox/。

用法（在装有客户端的 PC 上）：
    python tools/win_client_extract.py            # 提取全部可自动来源
    python tools/win_client_extract.py --inbox D:/share/ai-checkin-data/inbox

来源清单：
- 魔搭：~/.wb-switch/modelscope_login.json（wb-switch 捕获的 Cookie 全套）
- WPS灵犀 / 百度搭子 / MiniMax：推荐 `python -m app.main login <p> --headful`
  （Playwright 有头登录自动抓 Cookie），或浏览器 F12 手动复制。
- Qoder：本地存储加密（OSCrypt/envelope），无自动提取——抓包
  openapi.qoder.com.cn 任意请求，复制 Authorization: Bearer 后的串。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MODELSCOPE_LOGIN = Path.home() / '.wb-switch' / 'modelscope_login.json'


def extract_modelscope(inbox: Path) -> bool:
    if not MODELSCOPE_LOGIN.exists():
        print(f'未找到 {MODELSCOPE_LOGIN}，跳过魔搭')
        return False
    try:
        data = json.loads(MODELSCOPE_LOGIN.read_text(encoding='utf-8'))
    except Exception as exc:
        print(f'魔搭登录文件解析失败：{exc}')
        return False
    cookie = data.get('cookie') or data.get('Cookie') or ''
    token = data.get('sdk_token') or data.get('token') or ''
    if 'm_session_id' not in cookie:
        print('魔搭文件里没有 m_session_id，跳过')
        return False
    inbox.mkdir(parents=True, exist_ok=True)
    out = inbox / 'modelscope.json'
    creds = {'cookie': cookie}
    if token.startswith('ms-'):
        creds['token'] = token
    out.write_text(json.dumps(creds, ensure_ascii=False), encoding='utf-8')
    print(f'魔搭凭证 → {out}' + ('' if token else '\n  ⚠ 缺 SDK 令牌(ms-)，请去 modelscope.cn 个人中心复制'))
    return True


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    inbox = Path(sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == '--inbox'
                 else './inbox')
    ok = extract_modelscope(inbox)
    print('\n完成。' if ok else '\n未提取到凭证。')
    print('把 inbox/ 内容放到 NAS 共享目录 ai-checkin/data/inbox/ 即可被容器导入。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
