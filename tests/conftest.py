"""Shared fixtures. GDAL tests need the python3-gdal bindings, worker tests need onnx and onnxruntime."""
import hashlib
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))


def nearest4(batch):
    return np.repeat(np.repeat(batch, 4, axis=1), 4, axis=2).astype(np.float32)


class FakePredictor:
    """An exact 4x pixel repeat, with optional changes for failure tests."""

    def __init__(self, change=nearest4):
        self.change = change
        self.calls = 0
        self.info = {'backend': 'CPU'}

    def predict(self, batch):
        self.calls += 1
        return self.change(batch)

    def __call__(self, log_path):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def require_isolated_runtime():
    """The worker runs with -I. Skip if ONNX Runtime is only in the user site, which -I hides."""
    done = subprocess.run([sys.executable, '-I', '-c', 'import numpy, onnxruntime'], capture_output=True,
                          check=False)
    if done.returncode:
        pytest.skip('this interpreter cannot import onnxruntime in isolated mode')


def make_model(path, nan=False):
    """A real ONNX model with the plugin's tensor shape: 4x nearest neighbour, or all NaN."""
    onnx = pytest.importorskip('onnx')
    from onnx import TensorProto, helper, numpy_helper
    x = helper.make_tensor_value_info('rgb', TensorProto.FLOAT, [1, 3, 64, 64])
    y = helper.make_tensor_value_info('out', TensorProto.FLOAT, [1, 3, 256, 256])
    initializers = [numpy_helper.from_array(np.array([1, 1, 4, 4], np.float32), 'scales')]
    nodes = [helper.make_node('Resize', ['rgb', '', 'scales'], ['resized'], mode='nearest',
                              coordinate_transformation_mode='asymmetric', nearest_mode='floor')]
    if nan:
        initializers.append(numpy_helper.from_array(np.array(np.nan, np.float32), 'k'))
        nodes.append(helper.make_node('Add', ['resized', 'k'], ['out']))
    else:
        nodes.append(helper.make_node('Identity', ['resized'], ['out']))
    model = helper.make_model(helper.make_graph(nodes, 'g', [x], [y], initializers),
                              opset_imports=[helper.make_opsetid('', 17)])
    model.ir_version = 9
    onnx.checker.check_model(model)
    onnx.save(model, str(path))
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
