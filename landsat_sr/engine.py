# SPDX-License-Identifier: GPL-3.0-or-later
"""The processing pipeline. It does not import QGIS."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import shutil

import numpy as np

from . import publish, raster, tiling
from .constants import (BATCH, MODEL_NAME, MODEL_SHA256, NOTICE, PLUGIN_VERSION, SCALE, TILE, Cancelled,
                        SRError)

_STAGING_PREFIX = '.qgis_sr_'
_LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)
# 16-bit imagery often uses a few percent of its range. Each tile is stretched to its own range for
# the model and mapped back afterwards. A tile is never stretched more than 1 / _MIN_SPAN times,
# so that flat water or haze is not turned into strong noise.
_MIN_SPAN = 1.0 / 16
# A model may overshoot 0..1 a little. A value this far out means broken inference.
_SANE_LIMIT = 10.0


def check_prediction(prediction, count):
    """Reject broken model output before it can become ordinary pixels."""
    expected = (count, TILE * SCALE, TILE * SCALE, 3)
    if prediction.shape != expected or prediction.dtype != np.float32:
        raise SRError('The model returned data with an unexpected shape or type.')
    if not np.isfinite(prediction).all():
        raise SRError('The model returned NaN or infinite values. No output was written.')
    if np.abs(prediction).max() > _SANE_LIMIT:
        raise SRError('The model returned values far outside the image range. No output was written.')


def _prepare_rows(spec, y, rows, low, high):
    values, coverage = spec.read_rows(y, rows)
    valid = coverage > 0
    if valid.any():
        selected = values[valid]
        if selected.min() < low or selected.max() > high:
            raise SRError('Valid input pixels are outside the selected display range.')
    values[~valid] = low
    values = (values - low) / (high - low)
    if spec.mono:
        values = np.repeat(values, 3, axis=2)
    return values.astype(np.float32), coverage


def _condition(tile, valid, stretch):
    """The model input for one tile: (tile - offset) / span. Undo it as result * span + offset.

    Pixels without data get the mean of the valid pixels, so that the model sees no false black edge.
    """
    good = tile[valid]
    offset, span = 0.0, 1.0
    if stretch:
        low, high = float(good.min()), float(good.max())
        span = min(max(high - low, _MIN_SPAN), 1.0)
        offset = min(max((low + high - span) / 2, 0.0), 1.0 - span)
    prepared = ((tile - offset) / span).astype(np.float32)
    prepared[~valid] = (good.mean(axis=0) - offset) / span
    return np.clip(prepared, 0, 1), np.float32(offset), np.float32(span)


def _planes(spec, colour, coverage):
    """Convert blended output rows and input coverage to integer band planes."""
    colour = np.clip(colour, 0, 1)
    if spec.mono:
        colour = (colour @ _LUMA)[..., None]
    pixels = np.clip(colour * spec.type_max, 0, spec.type_max).round().astype(spec.dtype)
    if spec.has_transparency:  # no colour where the input has no data
        pixels[np.repeat(np.repeat(coverage <= 0, SCALE, axis=0), SCALE, axis=1)] = 0
    planes = [pixels[..., i] for i in range(pixels.shape[2])]
    if spec.has_transparency:
        alpha = (coverage * spec.type_max).round().astype(spec.dtype)
        alpha[(coverage > 0) & (alpha == 0)] = 1  # valid pixels never become invalid
        planes.append(np.repeat(np.repeat(alpha, SCALE, axis=0), SCALE, axis=1))
    return planes


def enlarge(spec, low, high, predictor, output, progress, canceled):
    """Stream the raster through the model. Returns (tiles predicted, invalid pixel count)."""
    ys, y_weights = tiling.axis_weights(spec.height)
    xs, x_weights = tiling.axis_weights(spec.width)
    tile_h, tile_w = min(TILE, spec.height), min(TILE, spec.width)
    acc = np.zeros((tile_h * SCALE, spec.width * SCALE, 3), np.float32)
    done_rows = 0  # input rows already written
    predicted = invalid = 0
    for row_number, y in enumerate(ys):
        if canceled():
            raise Cancelled()
        values, coverage = _prepare_rows(spec, y, tile_h, low, high)
        # A tile without one valid pixel only touches transparent output, so it needs no inference.
        wanted = [i for i, x in enumerate(xs) if coverage[:, x:x + tile_w].any()]
        for first in range(0, len(wanted), BATCH):
            if canceled():
                raise Cancelled()
            group = wanted[first:first + BATCH]
            prepared = [_condition(values[:, xs[i]:xs[i] + tile_w], coverage[:, xs[i]:xs[i] + tile_w] > 0,
                                   spec.type_max > 255) for i in group]
            batch = np.stack([tiling.pad_tile(item[0]) for item in prepared])
            result = predictor.predict(batch)
            check_prediction(result, len(group))
            predicted += len(group)
            for i, tile, (_, offset, span) in zip(group, result, prepared):
                part = tile[:tile_h * SCALE, :tile_w * SCALE] * span + offset
                weight = y_weights[row_number][:, None, None] * x_weights[i][None, :, None]
                left = xs[i] * SCALE
                top = (y - done_rows) * SCALE
                acc[top:top + tile_h * SCALE, left:left + tile_w * SCALE] += part * weight
            progress(100.0 * (row_number + (first + len(group)) / len(wanted)) / len(ys))
        next_y = ys[row_number + 1] if row_number + 1 < len(ys) else spec.height
        rows = next_y - done_rows  # no later tile touches these rows
        start = done_rows - y
        ready = coverage[start:start + rows]
        invalid += int((ready <= 0).sum())
        output.write(done_rows * SCALE, _planes(spec, acc[:rows * SCALE], ready))
        keep = acc.shape[0] - rows * SCALE
        if keep > 0:
            acc[:keep] = acc[rows * SCALE:].copy()
        acc[max(keep, 0):] = 0
        done_rows = next_y
        progress(100.0 * (row_number + 1) / len(ys))
    return predicted, invalid


def _make_staging(parent):
    """A new private folder next to the output.

    Not tempfile.mkdtemp: on Windows it retries about 2**31 times when the folder ACL denies new folders.
    """
    path = Path(os.path.abspath(parent)) / (_STAGING_PREFIX + secrets.token_hex(8))  # the worker has another cwd
    try:
        os.mkdir(path, 0o700)
    except OSError as exc:
        raise SRError('Cannot write to the output folder: {}. Choose another folder.'.format(
            exc.strerror or type(exc).__name__)) from exc
    return path


def run_job(options, predictor_factory, progress=lambda value: None, canceled=lambda: False):
    """Run one enlargement and publish the GeoTIFF and its report. Returns the report.

    predictor_factory(log_path) returns a context manager with predict(batch),
    close() semantics and an info dict (backend and runtime versions).
    """
    dest = Path(options['output'])
    if dest.suffix.lower() not in ('.tif', '.tiff'):
        raise SRError('Output must end in .tif or .tiff.')
    if not dest.parent.is_dir():
        raise SRError('Output folder does not exist.')
    publish.check_free(dest)
    source = raster.open_source(options['source'])
    spec = raster.SourceSpec(source, options.get('input_mode', 'auto'), options['bands'])
    auto_range = options.get('auto_range', True)
    low = 0.0 if auto_range else float(options['minimum'])
    high = float(spec.type_max) if auto_range else float(options['maximum'])
    if not (np.isfinite(low) and np.isfinite(high) and high > low):
        raise SRError('Display range maximum must exceed its minimum.')
    georeference = raster.Georeference(source)
    source_name = Path(options['source']).name
    created = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    metadata = raster.output_metadata({
        'TIFFTAG_SOFTWARE': 'SR Module for Landsat ' + PLUGIN_VERSION,
        'SR_MODEL': MODEL_NAME, 'SR_MODEL_SHA256': options.get('model_sha256', MODEL_SHA256),
        'SR_SOURCE_NAME': source_name, 'SR_DISPLAY_RANGE': '{:g} {:g}'.format(low, high),
        'SR_CREATED_UTC': created})

    staging_dir = _make_staging(dest.parent)
    output = None
    try:
        staging = staging_dir / 'result.tif'
        with predictor_factory(staging_dir / 'worker.log') as predictor:
            output = raster.OutputRaster(staging, spec, georeference, metadata)
            tiles, invalid = enlarge(spec, low, high, predictor, output, progress, canceled)
            info = dict(predictor.info)
        output.finish()
        extra_files = [p.name for p in staging_dir.iterdir() if p.name.startswith('result.') and p != staging]
        if extra_files:
            raise SRError('GDAL needs sidecar files for this raster, which is not supported: '
                          + ', '.join(extra_files))
        # An allowlist. Never copy the options: the source string and local paths can hold secrets.
        report = {
            'module': 'SR Module for Landsat', 'plugin_version': PLUGIN_VERSION, 'created_utc': created,
            'source_name': source_name, 'output_name': dest.name, 'scale': SCALE,
            'input_mode': 'mono' if spec.mono else 'rgb', 'processed_bands': spec.indexes,
            'auto_range': bool(auto_range), 'minimum': low, 'maximum': high,
            'output_bit_depth': 8 if spec.type_max == 255 else 16,
            'model_input_scaling': 'per tile' if spec.type_max > 255 else 'display range',
            'georeference': georeference.kind, 'model': MODEL_NAME,
            'model_sha256': metadata['SR_MODEL_SHA256'], 'requested_device': options.get('device', 'auto'),
            'backend': info.get('backend', 'unknown'),
            'runtime': {k: info[k] for k in ('python', 'numpy', 'onnxruntime') if k in info},
            'tiles_predicted': tiles, 'invalid_input_pixels': invalid, 'notice': NOTICE,
            'mask_note': ('Alpha follows the input. Predictions near transparent pixels can show errors.'
                          if spec.has_transparency else None),
        }
        report_staging = staging_dir / 'report.json'
        report_staging.write_text(json.dumps(report, indent=2), encoding='utf-8')
        if canceled():  # last chance: publication below is the commit point
            raise Cancelled()
        private = publish.publish_pair(staging, report_staging, dest)
        if private:  # for the caller only: the report file is already published
            report['private_files'] = private
        return report
    finally:
        if output is not None:
            output.close()
        shutil.rmtree(staging_dir, ignore_errors=True)
