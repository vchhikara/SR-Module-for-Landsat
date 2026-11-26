# SPDX-License-Identifier: GPL-3.0-or-later
"""One tile grid for the whole raster, with weights that sum to one.

Each tile is predicted once. The blend weight of a tile is wy(y) * wx(x), and
every tile in one row shares wy. The total weight therefore factors into
Ty(y) * Tx(x), so each axis can be normalised on its own. Rows can then be
written as soon as no later tile row touches them, and the result does not
depend on how the raster is split for processing.
"""
import numpy as np

from .constants import OVERLAP, SCALE, TILE


def starts(length, tile=TILE, overlap=OVERLAP):
    """First input pixel of every tile along one axis."""
    if length <= tile:
        return [0]
    out = list(range(0, length - tile + 1, tile - overlap))
    if out[-1] != length - tile:
        out.append(length - tile)
    return out


def axis_weights(length):
    """Return (starts, weights). weights[i] is the normalised taper of tile i, output pixels."""
    positions = starts(length)
    size = min(TILE, length) * SCALE
    ramp_length = min(OVERLAP * SCALE, size)
    ramp = np.linspace(0.001, 1.0, ramp_length, dtype=np.float32)
    total = np.zeros(length * SCALE, dtype=np.float32)
    raw = []
    for position in positions:
        weight = np.ones(size, np.float32)
        if position > 0:
            weight[:ramp_length] = ramp
        if position + TILE < length:
            weight[-ramp_length:] = np.minimum(weight[-ramp_length:], ramp[::-1])
        raw.append(weight)
        total[position * SCALE:position * SCALE + size] += weight
    return positions, [w / total[p * SCALE:p * SCALE + size] for p, w in zip(positions, raw)]


def pad_tile(patch):
    """Pad a (h, w, 3) patch to the model size by repeating the edge pixels."""
    height, width = patch.shape[:2]
    return np.pad(patch, ((0, TILE - height), (0, TILE - width), (0, 0)), mode='edge')
