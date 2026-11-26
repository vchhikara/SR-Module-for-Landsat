# SPDX-License-Identifier: GPL-3.0-or-later
"""Start the inference worker and talk to it over pipes, with deadlines and cancel."""
import json
from pathlib import Path
import queue
import struct
# Fixed argument lists, no shell.
import subprocess  # nosec B404
import threading
import time

import numpy as np

from . import runtime_config
from .constants import BATCH, SCALE, TILE, Cancelled, SRError
from .redact import redact

WORKER = Path(__file__).resolve().parent / 'stream_worker.py'
# CPU inference is slow, so the limits are generous. They only stop a hung worker.
STARTUP_TIMEOUT = 600.0
JOB_TIMEOUT = 900.0
_MAX_REPLY = BATCH * (TILE * SCALE) ** 2 * 3 * 4 + 65536
_POLL = 0.1


class Worker:
    """A context manager with predict(). The process never outlives the block."""

    def __init__(self, python, model, device, model_sha256, log_path, canceled=lambda: False,
                 startup_timeout=STARTUP_TIMEOUT, job_timeout=JOB_TIMEOUT, worker=WORKER):
        if device not in ('auto', 'gpu', 'cpu'):
            raise SRError('Unknown device.')
        self.log_path = Path(log_path)
        self.canceled = canceled
        self.job_timeout = job_timeout
        self.replies: queue.Queue = queue.Queue()
        self.info = {}
        root = Path(python).parent
        command = runtime_config.launch_args(python, self.log_path.parent / 'pycache') + [
            str(worker), str(model), device, model_sha256]
        self.log = open(self.log_path, 'wb')
        try:
            self.process = subprocess.Popen(  # nosec B603
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, cwd=str(root),
                env=runtime_config.clean_environment(root),
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except OSError as exc:
            self.log.close()
            raise SRError('The model worker did not start: {}'.format(exc.strerror or exc)) from exc
        if self.process.stdin is None or self.process.stdout is None:
            raise SRError('The model worker has no pipes.')
        self.stdin, self.stdout = self.process.stdin, self.process.stdout
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            kind, payload = self._wait(startup_timeout, 'start')
            if kind != b'R':
                self._fail(kind, payload)
            self.info = json.loads(payload)
        except BaseException:
            self.stop()
            raise

    def _read(self):
        stream = self.stdout
        try:
            while True:
                head = stream.read(5)
                if len(head) != 5:
                    break
                length = struct.unpack('<I', head[1:])[0]
                if length > _MAX_REPLY:
                    break
                payload = stream.read(length)
                if len(payload) != length:
                    break
                self.replies.put((head[:1], payload))
        except (OSError, ValueError):
            pass
        self.replies.put((None, b''))

    def _wait(self, timeout, stage):
        deadline = time.monotonic() + timeout
        while True:
            if self.canceled():
                raise Cancelled()
            try:
                return self.replies.get(timeout=_POLL)
            except queue.Empty:
                if time.monotonic() > deadline:
                    raise SRError('The model worker gave no answer within {:g} seconds ({}). '
                                  'It was stopped.'.format(timeout, stage) + self._log_tail()) from None

    def _log_tail(self):
        try:
            with open(self.log_path, 'rb') as handle:
                handle.seek(max(0, handle.seek(0, 2) - 3000))
                text = handle.read().decode('utf-8', 'replace').strip()
        except OSError:
            return ''
        return '\n' + redact(text) if text else ''

    def _fail(self, kind, payload):
        if kind == b'E':
            raise SRError('Model error:\n' + redact(payload.decode('utf-8', 'replace')))
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        raise SRError('The model worker stopped or sent an invalid reply.' + self._log_tail())

    def _send(self, data):
        """Write on a thread, so a stalled worker cannot block the deadline."""
        def write():
            try:
                self.stdin.write(data)
                self.stdin.flush()
            except (OSError, ValueError):
                pass  # the reader reports the stopped worker with its log
        threading.Thread(target=write, daemon=True).start()

    def predict(self, tiles):
        tiles = np.ascontiguousarray(tiles, np.float32)
        self._send(struct.pack('<I', len(tiles)) + tiles.tobytes())
        kind, payload = self._wait(self.job_timeout, 'inference')
        if kind != b'P':
            self._fail(kind, payload)
        header, _, data = payload.partition(b'\n')
        shape = (len(tiles), TILE * SCALE, TILE * SCALE, 3)
        if len(data) != int(np.prod(shape)) * 4:
            raise SRError('The model worker returned data of the wrong size.')
        self.info.update(backend=json.loads(header)['backend'])
        return np.frombuffer(data, np.float32).reshape(shape)

    def finish(self):
        """Ask the worker to exit and require a clean exit."""
        self._send(struct.pack('<I', 0))
        try:
            code = self.process.wait(timeout=30)
        except subprocess.TimeoutExpired as exc:
            raise SRError('The model worker did not exit.') from exc
        if code:
            raise SRError('The model worker failed during shutdown.' + self._log_tail())

    def stop(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        self.reader.join(timeout=5)
        for stream in (self.stdin, self.stdout):
            try:
                stream.close()
            except OSError:
                pass
        self.log.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            if exc_type is None:
                self.finish()
        finally:
            self.stop()
