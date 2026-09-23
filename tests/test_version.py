import re

from app import __version__
from app.main import main
from app.webapp import render_html


def test_version_is_semver():
    assert re.fullmatch(r'\d+\.\d+\.\d+', __version__)


def test_cli_version_prints_version(capsys):
    assert main(['version']) == 0
    assert __version__ in capsys.readouterr().out


def test_panel_footer_shows_version():
    status = {'done': 0, 'total': 0, 'today': '', 'platforms': []}
    html = render_html(status)
    assert f'v{__version__}' in html
