"""Playwright 把仪表盘 HTML 渲染成 PNG（容器内浏览器后台能力复用）。"""

from __future__ import annotations


def render_png(html: str) -> bytes:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 920, 'height': 640},
                                device_scale_factor=2)
        page.set_content(html)
        png = page.screenshot(full_page=True)
        browser.close()
    return png
