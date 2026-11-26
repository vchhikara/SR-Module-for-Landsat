# SPDX-License-Identifier: GPL-3.0-or-later
"""Isolated inference process. It runs in the SR runtime, not in QGIS Python.

It is started with -I and imports nothing from the plugin folder.
Request:  uint32 tile count, then count x 64 x 64 x 3 float32. Count 0 stops.
Reply:    1 byte kind, uint32 length, payload. Kinds: R ready (JSON),
          P predictions (JSON line, then float32 data), E error (UTF-8).
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import sys
import traceback

import numpy as np
import onnxruntime as ort

TILE_SHAPE = (64, 64, 3)
OUTPUT_SHAPE = (256, 256, 3)
MAX_TILES = 64


def load_model(path, expected_sha256):
    """Read the model once. The bytes that are hashed are the bytes that are loaded."""
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError('The model failed its integrity check.')
    return data


def create_session(model_bytes, device):
    options = ort.SessionOptions()
    options.enable_mem_pattern = False
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    providers = ['CPUExecutionProvider']
    if device == 'gpu':
        providers.insert(0, 'DmlExecutionProvider')
    session = ort.InferenceSession(model_bytes, sess_options=options, providers=providers)
    if device == 'gpu' and 'DmlExecutionProvider' not in session.get_providers():
        raise RuntimeError('DirectML GPU acceleration is unavailable on this computer.')
    return session


def predict_tiles(session, tiles):
    out = np.empty((len(tiles),) + OUTPUT_SHAPE, np.float32)
    name = session.get_inputs()[0].name
    for number, tile in enumerate(tiles):
        tensor = np.ascontiguousarray(tile.transpose(2, 0, 1)[None], dtype=np.float32)
        value = session.run(None, {name: tensor})[0]
        if value.shape != (1, 3) + OUTPUT_SHAPE[:2]:
            raise ValueError('Unexpected model output dimensions: {}'.format(value.shape))
        out[number] = value[0].transpose(1, 2, 0)
    if not np.isfinite(out).all():  # check before any clipping can hide it
        raise ValueError('The model returned NaN or infinite values.')
    return out


class Model:
    """A session with the 'auto' rule: DirectML first, CPU after any GPU failure."""

    def __init__(self, data, device):
        self.data, self.device = data, device
        if device == 'cpu':
            self._use_cpu()
            return
        try:
            self.session, self.backend = create_session(data, 'gpu'), 'DirectML GPU'
        except Exception:
            if device == 'gpu':
                raise
            traceback.print_exc()
            self._use_cpu()

    def _use_cpu(self):
        self.session, self.backend = create_session(self.data, 'cpu'), 'CPU'

    def predict(self, tiles):
        try:
            return predict_tiles(self.session, tiles)
        except Exception:
            if self.device != 'auto' or self.backend == 'CPU':
                raise
            traceback.print_exc()
            self._use_cpu()
            return predict_tiles(self.session, tiles)


def open_channel():
    """Keep stdout for the protocol only. Library messages go to the log."""
    descriptor = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    if sys.platform == 'win32':
        import msvcrt
        msvcrt.setmode(descriptor, os.O_BINARY)
    return os.fdopen(descriptor, 'wb')


def send(channel, kind, payload):
    channel.write(kind + struct.pack('<I', len(payload)) + payload)
    channel.flush()


def read_exact(stream, size):
    data = stream.read(size)
    if len(data) != size:
        raise EOFError('The request was cut short.')
    return data


def serve(model, requests, channel):
    while True:
        count = struct.unpack('<I', read_exact(requests, 4))[0]
        if count == 0:
            return
        if count > MAX_TILES:
            raise ValueError('Request is too large.')
        size = count * int(np.prod(TILE_SHAPE)) * 4
        tiles = np.frombuffer(read_exact(requests, size), np.float32).reshape((count,) + TILE_SHAPE)
        result = model.predict(tiles)
        header = json.dumps({'backend': model.backend}).encode() + b'\n'
        send(channel, b'P', header + result.tobytes())


def main(argv):
    model_path, device, expected_sha256 = argv
    channel = open_channel()
    try:
        model = Model(load_model(model_path, expected_sha256), device)
        info = {'backend': model.backend, 'python': platform.python_version(),
                'numpy': np.__version__, 'onnxruntime': ort.__version__}
        send(channel, b'R', json.dumps(info).encode())
        serve(model, sys.stdin.buffer, channel)
    except BaseException:
        traceback.print_exc()
        send(channel, b'E', traceback.format_exc()[-4000:].encode('utf-8', 'replace'))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
