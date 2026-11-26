# SPDX-License-Identifier: GPL-3.0-or-later
"""Values shared by the plugin, the worker launcher and the build scripts."""

PLUGIN_VERSION = '0.7.0'

MODEL_NAME = 'real-hat-sharper'
MODEL_FILE = 'real_hat_64.onnx'
# Public digest of the model file. weights/MODEL_SHA256.txt must match (tested).
MODEL_SHA256 = '3f47670dfeba712d68cd479f11cfe25866453c08b840269102b7a037eebc8908'  # pragma: allowlist secret

SCALE = 4
TILE = 64  # model input edge, input pixels
OVERLAP = 16  # input pixels shared by neighbouring tiles
BATCH = 4  # tiles in one worker request

MIN_RUNTIME_PYTHON = (3, 11)  # hashlib.file_digest and -P under -I

NOTICE = ('DERIVED VISUALIZATION. Detail is estimated by a super-resolution model. '
          'It is not measured data, not Landsat reflectance and not verified ground truth.')


class SRError(Exception):
    """A failure with a message that is safe and useful to show to the user."""


class Cancelled(SRError):
    def __init__(self):
        super().__init__('Cancelled.')
