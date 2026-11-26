# SPDX-License-Identifier: GPL-3.0-or-later
"""Select, check and pin the isolated inference runtime. QGIS Python is never modified.

A hash cannot show who made a runtime. The user decides to trust a runtime
folder once. The plugin then stores a fingerprint of every file in it and
refuses to start it if any file changes.
"""
import hashlib
import json
import os
from pathlib import Path
# Fixed argument lists, no shell.
import subprocess  # nosec B404
import tempfile

from .constants import MIN_RUNTIME_PYTHON, MODEL_FILE, MODEL_SHA256, SRError

BUNDLED_FINGERPRINT = 'runtime.sha256'  # written by the offline package builder
MAX_FILES = 60000
MAX_BYTES = 4 * 1024 ** 3
PROBE_TIMEOUT = 180
_ENV_KEEP = ('SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR', 'HOME', 'USERPROFILE',
             'LOCALAPPDATA', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'LANG', 'LC_ALL')

PROBE = '''
import json, struct, sys
import numpy, onnxruntime
print(json.dumps({'version': list(sys.version_info[:3]), 'bits': struct.calcsize('P') * 8,
    'paths': [p for p in sys.path if p] + [numpy.__file__, onnxruntime.__file__]}))
'''


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_paths(plugin_dir, configured_python='', configured_model=''):
    """Prefer explicit settings. Fall back to a self-contained plugin installation."""
    root = Path(plugin_dir)
    python = Path(configured_python) if configured_python else root / 'runtime' / 'python.exe'
    model = Path(configured_model) if configured_model else root / 'weights' / MODEL_FILE
    return python, model


def check_paths(python_path, model_path):
    """Cheap checks of the selected files. Nothing is executed."""
    python = Path(python_path) if python_path else None
    model = Path(model_path) if model_path else None
    if not python or not python.is_file():
        return 'Choose the Python executable from the SR runtime package.'
    if not model or not model.is_file():
        return 'Choose the real_hat_64.onnx model file from the SR runtime package.'
    if model.name.lower() != MODEL_FILE:
        return 'The selected model must be named real_hat_64.onnx.'
    try:
        digest = sha256_file(model)
    except OSError as exc:
        return 'Could not read the model file: {}'.format(exc.strerror or exc)
    if digest != MODEL_SHA256:
        return 'The selected model does not match the expected SHA-256. Choose the original model file.'
    return ''


def runtime_files(root):
    """Every file of a runtime tree, sorted. Links that leave the tree are refused."""
    root = Path(root).resolve()
    found, total = [], 0
    for folder, folders, names in os.walk(root):
        folders[:] = sorted(f for f in folders if f != '__pycache__')  # never loaded, see launch_args
        for name in sorted(names + [f for f in folders if os.path.islink(os.path.join(folder, f))]):
            path = Path(folder) / name
            target = path.resolve()
            if root not in target.parents:
                raise SRError('The runtime folder has a link that leaves the folder: {}'.format(
                    path.relative_to(root).as_posix()))
            if not target.is_file():
                continue
            total += target.stat().st_size
            found.append((path.relative_to(root).as_posix(), target))
            if len(found) > MAX_FILES or total > MAX_BYTES:
                raise SRError('This folder is too large to be an SR runtime. Select python.exe inside the '
                              'dedicated runtime folder of the SR package.')
    return sorted(found)


def fingerprint(root):
    digest = hashlib.sha256()
    try:
        for name, path in runtime_files(root):
            digest.update('{}\0{}\n'.format(name, sha256_file(path)).encode('utf-8'))
    except OSError as exc:
        raise SRError('Could not read the runtime folder: {}'.format(exc.strerror or exc)) from exc
    return digest.hexdigest()


def trusted_fingerprint(plugin_dir, python, stored_python, stored_fingerprint):
    """Return the fingerprint that this runtime must match, or '' if it was never trusted."""
    bundled = Path(plugin_dir) / 'runtime' / 'python.exe'
    if Path(python) == bundled:
        record = Path(plugin_dir) / BUNDLED_FINGERPRINT
        if record.is_file():
            return record.read_text(encoding='ascii').strip()
    if stored_fingerprint and str(python) == str(stored_python):
        return stored_fingerprint
    return ''


def verify_trusted(python, expected):
    if not expected:
        raise SRError('This runtime is not trusted yet. Open Configure SR runtime and model.')
    if fingerprint(Path(python).parent) != expected:
        raise SRError('The runtime files changed after you trusted them. Check where the change came '
                      'from, then configure the runtime again.')


def clean_environment(root):
    """A minimal environment: no PYTHON*, QT_*, ORT_* or user PATH entries."""
    env = {key: os.environ[key] for key in _ENV_KEEP if key in os.environ}
    if os.name == 'nt':
        system = os.environ.get('SYSTEMROOT', r'C:\Windows')
        env['PATH'] = os.pathsep.join([str(root), os.path.join(system, 'System32'), system])
    else:
        env['PATH'] = os.pathsep.join([str(root), '/usr/bin', '/bin'])
    return env


def launch_args(python, cache_dir):
    """-I ignores the user environment and site. pycache_prefix ignores __pycache__ in the runtime."""
    return [str(python), '-I', '-B', '-X', 'pycache_prefix=' + str(cache_dir)]


def probe(python, self_contained=True):
    """Run the trusted interpreter once and check version, architecture and imports."""
    root = Path(python).parent
    with tempfile.TemporaryDirectory() as cache:
        try:
            command = launch_args(python, cache) + ['-c', PROBE]
            # Runs only after the user trusted this interpreter.
            done = subprocess.run(command, capture_output=True, text=True, check=False,  # nosec B603
                                  timeout=PROBE_TIMEOUT, cwd=str(root), env=clean_environment(root),
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SRError('The runtime Python did not start: {}'.format(type(exc).__name__)) from exc
    if done.returncode:
        lines = done.stderr.strip().splitlines()
        raise SRError('The runtime check failed: {}'.format(lines[-1] if lines else done.returncode))
    try:
        info = json.loads(done.stdout.strip().splitlines()[-1])
        version, bits, paths = tuple(info['version']), info['bits'], info['paths']
    except (ValueError, KeyError, IndexError) as exc:
        raise SRError('The selected program did not answer like an SR runtime Python.') from exc
    if version < MIN_RUNTIME_PYTHON or bits != 64:
        raise SRError('The runtime needs 64-bit Python {}.{} or later. Found {}-bit {}.'.format(
            *MIN_RUNTIME_PYTHON, bits, '.'.join(map(str, version))))
    if self_contained:
        resolved = root.resolve()
        for item in paths:
            path = Path(item).resolve()
            if path != resolved and resolved not in path.parents:
                raise SRError('The runtime is not self-contained: it loads code from outside its folder.')
    return info
