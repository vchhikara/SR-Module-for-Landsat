# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a self-contained Windows package from an existing trusted runtime and model.

The package is not suitable for the QGIS plugin repository, which does not accept
binaries. A distributable build needs a rights record that confirms the right to
redistribute every third-party component. Without one, only an internal test
build is possible, and it is marked as not for distribution.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(Path(__file__).resolve().parent), str(ROOT)]
from release_files import PLUGIN_FOLDER, RELEASE_FILES, refuse_links  # noqa: E402
from package_plugin import add_member  # noqa: E402
from landsat_sr import constants, runtime_config  # noqa: E402

REQUIRED_COMPONENTS = ('python', 'numpy', 'onnxruntime', 'directml', 'model-weights')
REQUIRED_FIELDS = ('version', 'license', 'source', 'notice_file', 'confirmed_by', 'confirmed_on')
MARKER = 'DO_NOT_DISTRIBUTE.txt'


def check_rights(record_path):
    """Return {archive name: file} for the notices of a complete rights record."""
    record_path = Path(record_path)
    try:
        entries = {c['name']: c for c in json.loads(record_path.read_text(encoding='utf-8'))['components']}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError('The rights record cannot be read: {}'.format(exc)) from exc
    problems, notices = [], {}
    for name in REQUIRED_COMPONENTS:
        entry = entries.get(name)
        if entry is None:
            problems.append('{}: missing'.format(name))
            continue
        if entry.get('redistribution_confirmed') is not True:
            problems.append('{}: redistribution is not confirmed'.format(name))
        empty = [f for f in REQUIRED_FIELDS if not str(entry.get(f, '')).strip()]
        if empty:
            problems.append('{}: empty {}'.format(name, ', '.join(empty)))
            continue
        notice = record_path.parent / entry['notice_file']
        if not notice.is_file() or not notice.stat().st_size:
            problems.append('{}: notice file not found'.format(name))
        else:
            notices['licenses/{}.txt'.format(name)] = notice
    if problems:
        raise ValueError('Rights record incomplete: ' + '; '.join(problems))
    return notices


def build(source, bundle, output, rights_record=None, internal_test=False):
    source, bundle, output = Path(source), Path(bundle), Path(output)
    if bool(rights_record) == bool(internal_test):
        raise ValueError('Give a rights record, or ask for an internal test build.')
    notices = check_rights(rights_record) if rights_record else {}
    runtime, model = bundle / 'runtime', bundle / 'weights' / constants.MODEL_FILE
    if not (runtime / 'python.exe').is_file() or not model.is_file():
        raise ValueError('Expected runtime/python.exe and weights/real_hat_64.onnx in the runtime bundle')
    for folder in (source, runtime, bundle / 'weights'):
        refuse_links(folder)
    if runtime_config.sha256_file(model) != constants.MODEL_SHA256:
        raise ValueError('Model SHA-256 does not match the expected model')

    members = {name: source / name for name in RELEASE_FILES}
    members['weights/' + constants.MODEL_FILE] = model
    runtime_members = runtime_config.runtime_files(runtime)
    members.update({'runtime/' + name: path for name, path in runtime_members})
    members.update(notices)
    generated = {runtime_config.BUNDLED_FINGERPRINT:
                 (runtime_config.fingerprint(runtime) + '\n').encode('ascii')}
    if rights_record:
        generated['licenses/rights-record.json'] = Path(rights_record).read_bytes()
    else:
        generated[MARKER] = b'Internal test build. Redistribution rights are not confirmed.\n'
    manifest = {name: runtime_config.sha256_file(path) for name, path in members.items()}
    manifest.update({name: hashlib.sha256(data).hexdigest() for name, data in generated.items()})
    generated['MANIFEST.sha256'] = ''.join(
        '{}  {}\n'.format(manifest[name], name) for name in sorted(manifest)).encode('utf-8')

    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + '.part')
    try:
        with zipfile.ZipFile(partial, 'w') as archive:
            for name in sorted(set(members) | set(generated)):
                add_member(archive, PLUGIN_FOLDER + '/' + name,
                           generated[name] if name in generated else members[name])
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='landsat_sr')
    parser.add_argument('--bundle', required=True, help='Existing folder containing runtime/ and weights/')
    parser.add_argument('--output', required=True)
    parser.add_argument('--rights-record', help='Completed copy of docs/release/rights-record.template.json')
    parser.add_argument('--internal-test-build', action='store_true', help='Mark the ZIP as not distributable')
    args = parser.parse_args()
    print(build(args.source, args.bundle, args.output, args.rights_record, args.internal_test_build))
