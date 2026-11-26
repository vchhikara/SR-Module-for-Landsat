"""In-process worker logic: model bytes (L-01) and the GPU to CPU fallback."""
import hashlib

import numpy as np
import pytest

pytest.importorskip('onnxruntime')
from landsat_sr import stream_worker  # noqa: E402


def test_the_session_gets_the_bytes_that_were_hashed(tmp_path, monkeypatch):
    path = tmp_path / 'm.onnx'
    path.write_bytes(b'trusted bytes')
    data = stream_worker.load_model(path, hashlib.sha256(b'trusted bytes').hexdigest())
    path.write_bytes(b'swapped after the check')
    loaded = []

    def session(source, **kwargs):
        loaded.append(source)
        return object()
    monkeypatch.setattr(stream_worker.ort, 'InferenceSession', session)
    stream_worker.Model(data, 'cpu')
    assert loaded == [b'trusted bytes']


def sessions(monkeypatch, gpu_start_fails=False, gpu_run_fails=False, cpu_run_fails=False):
    made = []

    def create(data, device):
        if device == 'gpu' and gpu_start_fails:
            raise RuntimeError('no gpu')
        made.append(device)
        return device

    def predict(session, tiles):
        if (session == 'gpu' and gpu_run_fails) or (session == 'cpu' and cpu_run_fails):
            raise RuntimeError(session + ' failed')
        return np.zeros(1)
    monkeypatch.setattr(stream_worker, 'create_session', create)
    monkeypatch.setattr(stream_worker, 'predict_tiles', predict)
    return made


@pytest.mark.parametrize('failure', ['gpu_start_fails', 'gpu_run_fails'])
def test_auto_falls_back_to_cpu(monkeypatch, failure):
    sessions(monkeypatch, **{failure: True})
    model = stream_worker.Model(b'', 'auto')
    model.predict(None)
    assert model.backend == 'CPU'


@pytest.mark.parametrize('failure', ['gpu_start_fails', 'gpu_run_fails'])
def test_gpu_mode_never_falls_back(monkeypatch, failure):
    made = sessions(monkeypatch, **{failure: True})
    with pytest.raises(RuntimeError):
        stream_worker.Model(b'', 'gpu').predict(None)
    assert 'cpu' not in made


def test_auto_uses_the_gpu_when_it_works(monkeypatch):
    made = sessions(monkeypatch)
    model = stream_worker.Model(b'', 'auto')
    model.predict(None)
    assert model.backend == 'DirectML GPU' and made == ['gpu']


def test_a_cpu_failure_is_not_hidden(monkeypatch):
    sessions(monkeypatch, gpu_run_fails=True, cpu_run_fails=True)
    with pytest.raises(RuntimeError, match='cpu failed'):
        stream_worker.Model(b'', 'auto').predict(None)
