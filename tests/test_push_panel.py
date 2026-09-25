# -*- coding: utf-8 -*-
"""PC 推送工具：身份路由与平台过滤（2026-09-25 百度搭子裂号事故回归）。"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    'push_panel', _ROOT / 'tools' / 'push_panel.py')
pp = importlib.util.module_from_spec(_spec)
sys.dont_write_bytecode = True
_spec.loader.exec_module(pp)
sys.dont_write_bytecode = False


def make_jwt(payload: dict) -> str:
    import base64
    seg = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    return f'header.{seg}.sig'


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    d = tmp_path / 'inbox'
    d.mkdir()
    monkeypatch.setattr(pp, '_extract_trae_desktop', lambda: None)
    return d


def _wb(monkeypatch, accounts):
    monkeypatch.setattr(pp, 'scan_local_accounts', lambda _p: set())
    monkeypatch.setattr(pp, '_wb_switch_accounts', lambda: accounts)


def test_uidless_cookie_always_routes_main(inbox, monkeypatch):
    """无 JWT uid 的 Cookie 票：无论 wb 存档还是 inbox，一律钉死 main，绝不新增副号。"""
    _wb(monkeypatch, {'dazi': [{'cookie': 'OLD', 'label': '百度搭子-x'}]})
    (inbox / 'dazi.json').write_text(json.dumps({'cookie': 'NEW'}), encoding='utf-8')
    items = pp._collect(inbox, False)
    dazi = [b for p, b in items if p == 'dazi']
    assert dazi and all(b.get('id') == 'main' for b in dazi)


def test_uid_token_not_pinned_to_main(inbox, monkeypatch):
    """有 uid 的 token 平台不强制 main：交给 _route_id 按哈希/uid 路由。"""
    _wb(monkeypatch, {'trae': [{'token': make_jwt({'sub': 'U1'}), 'label': 'L'}]})
    items = pp._collect(inbox, False)
    trae = [b for p, b in items if p == 'trae']
    assert trae and all('id' not in b for b in trae)


def test_same_uid_merged_to_one_ticket(inbox, monkeypatch):
    """同 uid 两张票（wb 存档 + 桌面）归并成一条，取过期最远的。"""
    old = make_jwt({'sub': 'U1', 'exp': 1000})
    new = make_jwt({'sub': 'U1', 'exp': 9000})
    _wb(monkeypatch, {'trae': [{'token': old, 'label': 'L'}]})
    (inbox / 'trae.json').write_text(json.dumps({'token': new}), encoding='utf-8')
    items = pp._collect(inbox, False)
    tokens = [b['token'] for p, b in items if p == 'trae']
    assert tokens == [new]


def test_unsupported_platform_skipped(inbox, monkeypatch):
    """面板已下架的平台（linkai）直接跳过，不再白发 HTTPError。"""
    _wb(monkeypatch, {})
    (inbox / 'linkai.json').write_text(json.dumps({'cookie': 'X'}), encoding='utf-8')
    items = pp._collect(inbox, False)
    assert [p for p, _ in items] == []
