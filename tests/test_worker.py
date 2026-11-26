"""The real worker process and pipe protocol, with real ONNX Runtime and hostile fake workers."""
import json
import os
import sys
import textwrap
import time

import numpy as np
import pytest

from conftest import make_model, nearest4, require_isolated_runtime
from landsat_sr.constants import Cancelled, SRError
from landsat_sr.worker_client import Worker


@pytest.fixture(scope='module')
def model(tmp_path_factory):
    require_isolated_runtime()
    path = tmp_path_factory.mktemp('model') / 'real_hat_64.onnx'
    return path, make_model(path)


def start(tmp_path, model_path, sha, device='cpu', **kwargs):
    return Worker(sys.executable, model_path, device, sha, tmp_path / 'worker.log', **kwargs)


def fake_worker(tmp_path, body):
    script = tmp_path / 'fake_worker.py'
    script.write_text('import json, os, struct, sys, time\n'
                      'def send(kind, data):\n'
                      '    sys.stdout.buffer.write(kind + struct.pack("<I", len(data)) + data)\n'
                      '    sys.stdout.buffer.flush()\n' + textwrap.dedent(body))
    return script


READY = 'send(b"R", json.dumps({"backend": "CPU"}).encode())\n'


def hostile(tmp_path, body, **kwargs):
    return Worker(sys.executable, 'unused', 'cpu', 'unused', tmp_path / 'worker.log',
                  worker=fake_worker(tmp_path, body), **kwargs)


def batch(count=3):
    return np.random.default_rng(1).random((count, 64, 64, 3)).astype(np.float32)


@pytest.mark.parametrize('device', ['cpu', 'auto'])
def test_real_worker_returns_exact_pixels(tmp_path, model, device):
    with start(tmp_path, *model, device=device) as worker:
        for count in (4, 1, 3):
            tiles = batch(count)
            np.testing.assert_array_equal(worker.predict(tiles), nearest4(tiles))
        assert worker.info['backend'] == 'CPU'
        assert {'python', 'numpy', 'onnxruntime'} <= set(worker.info)
        process = worker.process
    assert process.returncode == 0


def test_gpu_mode_fails_loudly_without_directml(tmp_path, model):
    with pytest.raises(SRError, match='DirectML'):
        start(tmp_path, *model, device='gpu')


def test_wrong_model_digest_is_refused(tmp_path, model):
    with pytest.raises(SRError, match='integrity'):
        start(tmp_path, model[0], '0' * 64)


def test_nan_model_is_refused_inside_the_worker(tmp_path):
    require_isolated_runtime()
    path = tmp_path / 'real_hat_64.onnx'
    sha = make_model(path, nan=True)
    with pytest.raises(SRError, match='NaN'):
        with start(tmp_path, path, sha) as worker:
            worker.predict(batch(1))


def test_full_pipeline_with_the_real_worker(tmp_path, model):
    gdal = pytest.importorskip('osgeo.gdal')
    from landsat_sr import engine  # needs GDAL, which some CI jobs do not have
    data = np.random.default_rng(2).integers(0, 256, (3, 150, 210), np.uint8)
    source = str(tmp_path / 'in.tif')
    ds = gdal.GetDriverByName('GTiff').Create(source, 210, 150, 3, gdal.GDT_Byte)
    for i in range(3):
        ds.GetRasterBand(i + 1).WriteArray(data[i])
    ds = None
    report = engine.run_job(dict(source=source, output=str(tmp_path / 'out.tif'), bands=[1, 2, 3],
                                 model_sha256=model[1]),
                            lambda log: Worker(sys.executable, model[0], 'cpu', model[1], log))
    np.testing.assert_array_equal(gdal.Open(str(tmp_path / 'out.tif')).ReadAsArray(),
                                  np.repeat(np.repeat(data, 4, 1), 4, 2))
    assert report['backend'] == 'CPU' and report['runtime']['onnxruntime']
    assert sorted(p.name for p in tmp_path.iterdir()) == ['in.tif', 'out.tif', 'out.tif.json']


# ---- M-03 liveness and hostile replies ----------------------------------------

@pytest.mark.parametrize('body', [
    READY + 'time.sleep(60)\n',                          # never reads the request
    READY + 'sys.stdin.buffer.read()\n',                 # reads, never answers
], ids=['deaf', 'silent'])
def test_a_hung_worker_is_stopped_at_the_deadline(tmp_path, body):
    began = time.monotonic()
    with pytest.raises(SRError, match='gave no answer'):
        with hostile(tmp_path, body, job_timeout=1.5) as worker:
            process = worker.process
            worker.predict(batch(4))
    assert time.monotonic() - began < 15 and process.poll() is not None


def test_a_worker_that_never_starts_times_out(tmp_path):
    with pytest.raises(SRError, match='start'):
        hostile(tmp_path, 'time.sleep(60)\n', startup_timeout=1)


def test_cancel_stops_a_hung_worker(tmp_path):
    flag = {'cancel': False}
    with pytest.raises(Cancelled):
        with hostile(tmp_path, READY + 'time.sleep(60)\n', canceled=lambda: flag['cancel']) as worker:
            process = worker.process
            flag['cancel'] = True
            worker.predict(batch(1))
    assert process.poll() is not None


@pytest.mark.parametrize('body,match', [
    (READY + 'sys.stderr.write("native crash marker\\n"); os._exit(3)\n', 'native crash marker'),
    (READY + 'sys.stdin.buffer.read(4); sys.stdout.buffer.write(b"P\\xff\\xff\\xff\\xff"); '
     'sys.stdout.flush(); time.sleep(30)\n', 'invalid reply'),
    (READY + 'sys.stdin.buffer.read(4 + 49152); send(b"P", b\'{"backend":"CPU"}\\nshort\'); time.sleep(30)\n',
     'wrong size'),
    (READY + 'sys.stdin.buffer.read(4 + 49152); send(b"Z", b""); time.sleep(30)\n', 'invalid reply'),
    ('print("not a frame"); time.sleep(0.2)\n', 'invalid reply'),
], ids=['crash', 'huge', 'short', 'unknown-kind', 'garbage'])
def test_broken_replies_fail_with_a_message(tmp_path, body, match):
    with pytest.raises(SRError, match=match):
        with hostile(tmp_path, body, job_timeout=20) as worker:
            worker.predict(batch(1))


def test_worker_errors_are_redacted(tmp_path):
    with pytest.raises(SRError) as caught:
        hostile(tmp_path, 'send(b"E", b"failed for https://u:hunter2@host/x?token=abc")\n')
    assert 'hunter2' not in str(caught.value) and 'abc' not in str(caught.value)


# ---- M-02 isolation of the child ------------------------------------------------

def test_child_gets_a_clean_environment_and_runtime_folder(tmp_path, monkeypatch):
    for key in ('PYTHONPATH', 'PYTHONSTARTUP', 'PYTHONUSERBASE', 'QT_PLUGIN_PATH', 'ORT_DYLIB_PATH',
                'LD_PRELOAD', 'LD_LIBRARY_PATH', 'SR_SECRET'):
        monkeypatch.setenv(key, str(tmp_path))
    monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ['PATH'])
    body = ('send(b"R", json.dumps({"env": dict(os.environ), "cwd": os.getcwd(), '
            '"isolated": sys.flags.isolated, "prefix": sys.pycache_prefix}).encode())\ntime.sleep(30)\n')
    worker = hostile(tmp_path, body)
    try:
        info = worker.info
    finally:
        worker.stop()
    leaked = {k for k in info['env'] if k.startswith(('PYTHON', 'QT_', 'ORT_', 'LD_', 'SR_'))}
    assert not leaked and str(tmp_path) not in info['env']['PATH']
    assert info['isolated'] == 1
    assert os.path.samefile(info['cwd'], os.path.dirname(sys.executable))
    assert info['prefix'] and json.dumps(info['prefix'])
