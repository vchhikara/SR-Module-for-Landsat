"""Tests of runtime selection and model-integrity checks."""
import hashlib
from pathlib import Path

from landsat_sr import runtime_config


def test_default_and_explicit_paths(tmp_path):
    python, model = runtime_config.resolve_paths(tmp_path)
    assert python == tmp_path / 'runtime' / 'python.exe'
    assert model == tmp_path / 'weights' / 'real_hat_64.onnx'
    selected = runtime_config.resolve_paths(tmp_path, str(tmp_path / 'external.exe'), str(tmp_path / 'real_hat_64.onnx'))
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
