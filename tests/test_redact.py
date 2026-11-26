import pytest

from landsat_sr.redact import redact


@pytest.mark.parametrize('text', [
    'https://user:hunter2@example.invalid/raster',
    'https://example.invalid/raster?key=hunter2&x=1',
    "dbname=gis user=bob password='hunter2' table=x",
    'url=http://h/wms&authcfg=hunter2',
    'AWS_SECRET_ACCESS_KEY=hunter2',
    'access_token: hunter2',
    'Authorization: Bearer hunter2',
    'PG:host=h password=hunter2',
    '/vsicurl/https://h/a.tif?sig=hunter2',
    '{"password": "hunter2"}',
    '"access_token":"hunter2"',
    "config={'apikey': 'hunter2'}",
])
def test_secrets_are_removed(text):
    assert 'hunter2' not in redact(text)


@pytest.mark.parametrize('text', [
    'Selected band 4 does not exist.',
    'Could not read C:\\data\\monkey\\scene.tif',
    'keyboard=interrupt',
])
def test_ordinary_text_is_kept(text):
    assert redact(text) == text
