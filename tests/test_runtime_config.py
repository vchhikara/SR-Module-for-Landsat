"""Runtime selection, trust pinning and probing (M-02, M-08)."""
import hashlib
import os
from pathlib import Path
import stat
import sys

import pytest

from conftest import require_isolated_runtime
from landsat_sr import constants, runtime_config
from landsat_sr.constants import SRError

ROOT = Path(__file__).resolve().parents[1]
posix_only = pytest.mark.skipif(os.name == 'nt', reason='uses a shell script as a fake interpreter')


def test_default_and_explicit_paths(tmp_path):
    python, model = runtime_config.resolve_paths(tmp_path)
    assert python == tmp_path / 'runtime' / 'python.exe'
    assert model == tmp_path / 'weights' / 'real_hat_64.onnx'
    selected = runtime_config.resolve_paths(tmp_path, str(tmp_path / 'external.exe'),
                                            str(tmp_path / 'real_hat_64.onnx'))
    assert selected == (tmp_path / 'external.exe', tmp_path / 'real_hat_64.onnx')


def test_paths_and_model_integrity(tmp_path, monkeypatch):
    exe = tmp_path / 'python.exe'
    model = tmp_path / 'real_hat_64.onnx'
    assert 'Python executable' in runtime_config.check_paths(str(exe), str(model))
    exe.write_bytes(b'python')
    assert 'model file' in runtime_config.check_paths(str(exe), str(model))
    model.write_bytes(b'wrong')
    assert 'SHA-256' in runtime_config.check_paths(str(exe), str(model))
    monkeypatch.setattr(runtime_config, 'MODEL_SHA256', hashlib.sha256(b'wrong').hexdigest())
    assert runtime_config.check_paths(str(exe), str(model)) == ''
    other = tmp_path / 'different.onnx'
    other.write_bytes(b'wrong')
    assert 'must be named' in runtime_config.check_paths(str(exe), str(other))


def test_the_published_digest_matches_the_code():
    text = (ROOT / 'landsat_sr' / 'weights' / 'MODEL_SHA256.txt').read_text(encoding='ascii')
    assert text.split() == [constants.MODEL_SHA256, constants.MODEL_FILE]


def tree(tmp_path):
    root = tmp_path / 'runtime'
    (root / 'Lib').mkdir(parents=True)
    (root / 'python.exe').write_bytes(b'exe')
    (root / 'Lib' / 'os.py').write_bytes(b'code')
    return root


@pytest.mark.parametrize('change', [
    lambda r: (r / 'Lib' / 'os.py').write_bytes(b'evil'),
    lambda r: (r / 'added.dll').write_bytes(b'dll'),
    lambda r: (r / 'sitecustomize.py').write_bytes(b'x'),
    lambda r: (r / 'Lib' / 'os.py').unlink(),
    lambda r: (r / 'Lib' / 'os.py').rename(r / 'Lib' / 'other.py'),
], ids=['modify', 'add-dll', 'add-py', 'delete', 'rename'])
def test_any_change_to_a_trusted_runtime_blocks_it(tmp_path, change):
    root = tree(tmp_path)
    recorded = runtime_config.fingerprint(root)
    runtime_config.verify_trusted(root / 'python.exe', recorded)
    change(root)
    with pytest.raises(SRError, match='changed after you trusted'):
        runtime_config.verify_trusted(root / 'python.exe', recorded)


def test_pycache_is_ignored_because_the_child_never_reads_it(tmp_path):
    root = tree(tmp_path)
    recorded = runtime_config.fingerprint(root)
    (root / 'Lib' / '__pycache__').mkdir()
    (root / 'Lib' / '__pycache__' / 'os.cpython-312.pyc').write_bytes(b'planted')
    assert runtime_config.fingerprint(root) == recorded
    args = runtime_config.launch_args(root / 'python.exe', tmp_path / 'empty')
    assert '-I' in args and 'pycache_prefix=' + str(tmp_path / 'empty') in args


def test_untrusted_runtime_is_refused(tmp_path):
    root = tree(tmp_path)
    with pytest.raises(SRError, match='not trusted'):
        runtime_config.verify_trusted(root / 'python.exe', '')


def test_trust_follows_the_selected_path_only(tmp_path):
    plugin = tmp_path / 'plugin'
    plugin.mkdir()
    assert runtime_config.trusted_fingerprint(plugin, '/a/python.exe', '/a/python.exe', 'abc') == 'abc'
    assert runtime_config.trusted_fingerprint(plugin, '/b/python.exe', '/a/python.exe', 'abc') == ''
    bundled = plugin / 'runtime' / 'python.exe'
    assert runtime_config.trusted_fingerprint(plugin, bundled, '', '') == ''
    (plugin / 'runtime.sha256').write_text('shipped\n')
    assert runtime_config.trusted_fingerprint(plugin, bundled, '', '') == 'shipped'


@posix_only
def test_a_link_that_leaves_the_runtime_is_refused(tmp_path):
    root = tree(tmp_path)
    (tmp_path / 'outside').write_bytes(b'private')
    (root / 'link').symlink_to(tmp_path / 'outside')
    with pytest.raises(SRError, match='leaves the folder'):
        runtime_config.fingerprint(root)


def test_a_huge_folder_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_config, 'MAX_FILES', 1)
    with pytest.raises(SRError, match='too large'):
        runtime_config.fingerprint(tree(tmp_path))


def fake_interpreter(tmp_path, output, code=0):
    script = tmp_path / 'python.exe'
    script.write_text("#!/bin/sh\ncat <<'EOF'\n{}\nEOF\nexit {}\n".format(output, code))
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


@posix_only
@pytest.mark.parametrize('output,match', [
    ('{"version": [3, 10, 9], "bits": 64, "paths": []}', '3.11 or later'),
    ('{"version": [3, 12, 0], "bits": 32, "paths": []}', '64-bit'),
    ('hello', 'did not answer like'),
    ('{"version": [3, 12, 0], "bits": 64, "paths": ["/usr/lib/python3"]}', 'not self-contained'),
])
def test_probe_refuses_unsuitable_runtimes(tmp_path, output, match):
    with pytest.raises(SRError, match=match):
        runtime_config.probe(fake_interpreter(tmp_path, output))


@posix_only
def test_probe_reports_a_failing_interpreter(tmp_path):
    with pytest.raises(SRError, match='check failed'):
        runtime_config.probe(fake_interpreter(tmp_path, '', 1))


def test_probe_reads_a_real_interpreter():
    require_isolated_runtime()
    info = runtime_config.probe(sys.executable, self_contained=False)
    assert info['bits'] == 64 and tuple(info['version']) == sys.version_info[:3]
