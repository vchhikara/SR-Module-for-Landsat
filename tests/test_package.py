"""Package tests. They need no QGIS."""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import package_plugin  # noqa: E402
import validate_plugin  # noqa: E402


def test_source_tree_is_valid():
    assert validate_plugin.validate_tree(ROOT / 'landsat_sr') == []


def test_zip_layout_and_no_binaries(tmp_path):
    output = package_plugin.package_plugin(ROOT / 'landsat_sr', tmp_path / 'landsat_sr.zip')
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
    assert names
    assert all(name.startswith('landsat_sr/') for name in names)
    assert 'landsat_sr/metadata.txt' in names
    assert not [n for n in names if n.endswith(('.onnx', '.exe', '.dll', '.pyc'))]


def test_zip_is_reproducible(tmp_path):
    a = package_plugin.package_plugin(ROOT / 'landsat_sr', tmp_path / 'a.zip')
    b = package_plugin.package_plugin(ROOT / 'landsat_sr', tmp_path / 'b.zip')
    assert a.read_bytes() == b.read_bytes()


def test_worker_process_keeps_its_pipes():
    """A trailing comment must not swallow the Popen arguments."""
    import ast
    source = (ROOT / 'landsat_sr' / 'plugin.py').read_text(encoding='utf-8')
    calls = [n for n in ast.walk(ast.parse(source))
             if isinstance(n, ast.Call) and getattr(n.func, 'attr', '') == 'Popen']
    assert len(calls) == 1
    assert {'stdin', 'stdout', 'stderr', 'env'} <= {k.arg for k in calls[0].keywords}
