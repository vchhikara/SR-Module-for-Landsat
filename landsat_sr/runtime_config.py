"""Resolve the isolated inference runtime without modifying the QGIS Python environment."""
import hashlib
from pathlib import Path

MODEL_SHA256 = '3f47670dfeba712d68cd479f11cfe25866453c08b840269102b7a037eebc8908'


def check_paths(python_path, model_path):
    """Validate files selected by the user before the worker is launched."""
    python = Path(python_path) if python_path else None
    model = Path(model_path) if model_path else None
    if not python or not python.is_file():
        return 'Choose the Python executable from the SR runtime package.'
    if not model or not model.is_file():
        return 'Choose the real_hat_64.onnx model file from the SR runtime package.'
    if model.name.lower() != 'real_hat_64.onnx':
        return 'The selected model must be named real_hat_64.onnx.'
    try:
        digest = hashlib.sha256()
        with model.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
    except OSError as exc:
        return 'Could not read the model file: {}'.format(exc)
    if digest.hexdigest() != MODEL_SHA256:
        return 'The selected model does not match the expected SHA-256. Choose the original model file.'
    return ''


def resolve_paths(plugin_dir, configured_python='', configured_model=''):
    """Prefer explicit settings; fall back to a self-contained plugin installation."""
    root = Path(plugin_dir)
    python = Path(configured_python) if configured_python else root / 'runtime' / 'python.exe'
    model = Path(configured_model) if configured_model else root / 'weights' / 'real_hat_64.onnx'
    return python, model
