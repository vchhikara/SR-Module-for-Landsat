"""Package builders and validator (M-06, M-07, L-02, M-10). They need no QGIS."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile

import pytest

import package_offline_windows as offline
import package_plugin
import release_files
import validate_plugin
from landsat_sr import constants, runtime_config

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'landsat_sr'


def copy_source(tmp_path):
    target = tmp_path / 'landsat_sr'
    shutil.copytree(SOURCE, target, ignore=shutil.ignore_patterns('__pycache__'))
    return target


def test_source_tree_is_valid():
    assert validate_plugin.validate_tree(SOURCE) == []


def test_every_local_import_is_a_release_file():
    for name in release_files.RELEASE_FILES:
        if name.endswith('.py'):
            for line in (SOURCE / name).read_text(encoding='utf-8').splitlines():
                if line.startswith('from . import '):
                    for module in line.split('import ')[1].split(','):
                        assert module.strip() + '.py' in release_files.RELEASE_FILES
                elif line.startswith('from .'):
                    assert line.split()[1][1:] + '.py' in release_files.RELEASE_FILES


def test_versions_agree():
    metadata = (SOURCE / 'metadata.txt').read_text(encoding='utf-8')
    assert 'version={}\n'.format(constants.PLUGIN_VERSION) in metadata
    assert '## ' + constants.PLUGIN_VERSION in (SOURCE / 'CHANGELOG.md').read_text(encoding='utf-8')


def test_zip_is_exact_and_reproducible(tmp_path):
    a = package_plugin.package_plugin(SOURCE, tmp_path / 'a.zip')
    copied = copy_source(tmp_path)
    os.utime(copied / 'plugin.py', (1, 1))
    b = package_plugin.package_plugin(copied, tmp_path / 'b.zip')
    assert a.read_bytes() == b.read_bytes()
    with zipfile.ZipFile(a) as archive:
        assert sorted(archive.namelist()) == sorted('landsat_sr/' + n for n in release_files.RELEASE_FILES)


@pytest.mark.parametrize('name,data', [
    ('native.DLL', b'x'), ('tool.EXE', b'x'), ('m.OnNx', b'x'), ('lib.So', b'x'), ('x.Pyd', b'x'),
    ('extra.py', b'print()'), ('noext', b'MZ\x90\x00'), ('noext2', b'\x7fELF'), ('.hidden/x.py', b''),
])
def test_validator_rejects_every_extra_member(tmp_path, name, data):
    good = package_plugin.package_plugin(SOURCE, tmp_path / 'good.zip')
    assert validate_plugin.validate_zip(good) == []
    with zipfile.ZipFile(good, 'a') as archive:
        archive.writestr('landsat_sr/' + name, data)
    assert validate_plugin.validate_zip(good)
    tree = copy_source(tmp_path)
    (tree / name).parent.mkdir(exist_ok=True)
    (tree / name).write_bytes(data)
    assert validate_plugin.validate_tree(tree)


def test_validator_rejects_a_binary_hidden_under_an_allowed_name(tmp_path):
    tree = copy_source(tmp_path)
    (tree / 'redact.py').write_bytes(b'MZ\x90\x00')
    assert any('Binary' in e for e in validate_plugin.validate_tree(tree))


@pytest.mark.parametrize('name', ['../evil.py', '/abs.py', 'other/__init__.py'])
def test_validator_rejects_unsafe_locations(tmp_path, name):
    good = package_plugin.package_plugin(SOURCE, tmp_path / 'good.zip')
    with zipfile.ZipFile(good, 'a') as archive:
        archive.writestr(name, b'')
    assert validate_plugin.validate_zip(good)


# ---- offline builder ------------------------------------------------------------

@pytest.fixture()
def bundle(tmp_path, monkeypatch):
    root = tmp_path / 'bundle'
    (root / 'runtime' / 'Lib' / '__pycache__').mkdir(parents=True)
    (root / 'weights').mkdir()
    (root / 'runtime' / 'python.exe').write_bytes(b'MZ fake')
    (root / 'runtime' / 'Lib' / 'a.py').write_bytes(b'a')
    (root / 'runtime' / 'Lib' / 'legacy.pyc').write_bytes(b'sourceless')
    (root / 'runtime' / 'Lib' / '__pycache__' / 'a.pyc').write_bytes(b'cache')
    (root / 'weights' / 'real_hat_64.onnx').write_bytes(b'fake model')
    monkeypatch.setattr(constants, 'MODEL_SHA256', hashlib.sha256(b'fake model').hexdigest())
    return root


def rights(tmp_path, **override):
    (tmp_path / 'notice.txt').write_text('license text')
    components = []
    for name in offline.REQUIRED_COMPONENTS:
        entry = {'name': name, 'version': '1', 'license': 'x', 'source': 'y', 'notice_file': 'notice.txt',
                 'confirmed_by': 'owner', 'confirmed_on': '2026-11-26', 'redistribution_confirmed': True}
        entry.update(override if name == 'model-weights' else {})
        components.append(entry)
    path = tmp_path / 'rights.json'
    path.write_text(json.dumps({'components': components}))
    return path


@pytest.mark.parametrize('override', [{'redistribution_confirmed': False}, {'redistribution_confirmed': 'yes'},
                                      {'license': ''}, {'notice_file': 'missing.txt'}])
def test_incomplete_rights_block_a_distributable_build(tmp_path, bundle, override):
    with pytest.raises(ValueError, match='Rights record incomplete'):
        offline.build(SOURCE, bundle, tmp_path / 'o.zip', rights_record=rights(tmp_path, **override))
    assert not (tmp_path / 'o.zip').exists()


def test_the_unfilled_template_is_refused(tmp_path, bundle):
    with pytest.raises(ValueError, match='Rights record incomplete'):
        offline.build(SOURCE, bundle, tmp_path / 'o.zip',
                      rights_record=ROOT / 'docs' / 'release' / 'rights-record.template.json')


def test_a_build_needs_rights_or_the_internal_flag(tmp_path, bundle):
    with pytest.raises(ValueError, match='rights record'):
        offline.build(SOURCE, bundle, tmp_path / 'o.zip')


def test_offline_zip_is_reproducible_marked_and_trusted(tmp_path, bundle):
    a = offline.build(SOURCE, bundle, tmp_path / 'a.zip', internal_test=True)
    for path in bundle.rglob('*'):
        os.utime(path, (5, 5))
    b = offline.build(SOURCE, bundle, tmp_path / 'b.zip', internal_test=True)
    assert a.read_bytes() == b.read_bytes()
    with zipfile.ZipFile(a) as archive:  # no clock or file time may reach the ZIP
        assert {(i.date_time, i.external_attr) for i in archive.infolist()} == {
            ((2020, 1, 1, 0, 0, 0), 0o100644 << 16)}
    extracted = tmp_path / 'x'
    with zipfile.ZipFile(a) as archive:
        names = archive.namelist()
        archive.extractall(extracted)
    plugin = extracted / 'landsat_sr'
    assert 'landsat_sr/DO_NOT_DISTRIBUTE.txt' in names
    assert not [n for n in names if '__pycache__' in n]
    runtime_config.verify_trusted(plugin / 'runtime' / 'python.exe', runtime_config.trusted_fingerprint(
        plugin, plugin / 'runtime' / 'python.exe', '', ''))
    for line in (plugin / 'MANIFEST.sha256').read_text().splitlines():
        digest, name = line.split('  ')
        assert runtime_config.sha256_file(plugin / name) == digest


def test_distributable_build_ships_the_notices(tmp_path, bundle):
    out = offline.build(SOURCE, bundle, tmp_path / 'o.zip', rights_record=rights(tmp_path))
    with zipfile.ZipFile(out) as archive:
        names = archive.namelist()
    assert 'landsat_sr/licenses/model-weights.txt' in names
    assert 'landsat_sr/DO_NOT_DISTRIBUTE.txt' not in names


@pytest.mark.skipif(os.name == 'nt', reason='symlinks need privileges on Windows')
@pytest.mark.parametrize('is_dir', [False, True])
def test_offline_builder_refuses_links(tmp_path, bundle, is_dir):
    outside = tmp_path / 'private'
    if is_dir:
        outside.mkdir()
        (outside / 'secret').write_text('SECRET')
    else:
        outside.write_text('SECRET')
    (bundle / 'runtime' / 'link').symlink_to(outside, target_is_directory=is_dir)
    with pytest.raises(ValueError, match='Links are not allowed'):
        offline.build(SOURCE, bundle, tmp_path / 'o.zip', internal_test=True)
    assert not (tmp_path / 'o.zip').exists()


def test_a_failed_offline_build_leaves_no_partial_zip(tmp_path, bundle, monkeypatch):
    real = offline.add_member
    count = {'n': 0}

    def fail_later(archive, name, source):
        count['n'] += 1
        if count['n'] == 3:
            raise OSError('disk full')
        real(archive, name, source)
    monkeypatch.setattr(offline, 'add_member', fail_later)
    with pytest.raises(OSError):
        offline.build(SOURCE, bundle, tmp_path / 'o.zip', internal_test=True)
    assert not (tmp_path / 'o.zip').exists()


def test_wrong_model_is_refused(tmp_path, bundle):
    (bundle / 'weights' / 'real_hat_64.onnx').write_bytes(b'other')
    with pytest.raises(ValueError, match='SHA-256'):
        offline.build(SOURCE, bundle, tmp_path / 'o.zip', internal_test=True)
