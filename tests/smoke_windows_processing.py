"""Manual: real QGIS, GDAL and the real model with an explicitly supplied runtime package.

Set LANDSAT_SR_RUNTIME_PACKAGE to a folder with runtime/ and weights/. This runs the runtime.
Optional: LANDSAT_SR_TEST_DEVICE (cpu, auto, gpu). Run it with the QGIS Python.
"""
import json
import os
from pathlib import Path
import sys
import tempfile

import numpy as np
from osgeo import gdal, osr
from qgis.core import QgsApplication

sys.path.insert(0, os.environ.get('LANDSAT_SR_TEST_PLUGIN_ROOT', str(Path(__file__).resolve().parents[1])))
from landsat_sr import runtime_config  # noqa: E402
from landsat_sr.plugin import RunTask  # noqa: E402

bundle = Path(os.environ['LANDSAT_SR_RUNTIME_PACKAGE'])
device = os.environ.get('LANDSAT_SR_TEST_DEVICE', 'cpu')
python = bundle / 'runtime' / 'python.exe'
model = bundle / 'weights' / 'real_hat_64.onnx'
assert runtime_config.check_paths(str(python), str(model)) == ''
print('runtime:', runtime_config.probe(python)['version'], flush=True)  # must be self-contained
trusted = runtime_config.fingerprint(python.parent)
app = QgsApplication([], False)
app.initQgis()
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    # (name, colour bands, alpha value or None, size, value scale). The large sizes need several tiles.
    # A scale above 1 gives UInt16 data in a narrow part of 0..65535, like Landsat land values.
    for name, channels, alpha, size, scale in [('rgb', 3, None, 8, 1), ('mono', 1, None, 8, 1),
                                               ('rgba_large', 3, 127, 210, 1), ('mono_large', 1, None, 150, 1),
                                               ('rgb_uint16', 3, None, 210, 16)]:
        source = root / (name + '_input.tif')
        destination = root / (name + '_output.tif')
        bands = channels + (alpha is not None)
        base, datatype = (7000, gdal.GDT_UInt16) if scale > 1 else (0, gdal.GDT_Byte)
        ds = gdal.GetDriverByName('GTiff').Create(str(source), size, size, bands, datatype,
                                                  options=['PHOTOMETRIC=RGB', 'ALPHA=YES'] if alpha else [])
        ds.SetGeoTransform((10, 30, 2, 20, 1, -30))
        crs = osr.SpatialReference()
        crs.ImportFromEPSG(32643)
        ds.SetProjection(crs.ExportToWkt())
        ramp = (np.add.outer(np.arange(size), np.arange(size)) % 180 + 40).astype(np.uint8)
        for i in range(channels):
            ds.GetRasterBand(i + 1).WriteArray(base + (ramp + i).astype(np.uint16) * scale)
        if alpha:
            ds.GetRasterBand(bands).Fill(alpha)
        ds = None
        options = dict(source=str(source), output=str(destination), bands=[1, 2, 3],
                       input_mode='rgb' if channels == 3 else 'mono', auto_range=True, minimum=0, maximum=255,
                       python=str(python), model_path=str(model), runtime_fingerprint=trusted,
                       device=device, add=False)
        task = RunTask(options, None)
        assert task.run(), task.error + '\n' + task.debug_traceback
        ds = gdal.Open(str(destination))
        out = ds.ReadAsArray()
        out = out if out.ndim == 3 else out[None]
        assert (ds.RasterXSize, ds.RasterYSize, ds.RasterCount) == (size * 4, size * 4, bands)
        assert ds.GetGeoTransform() == (10.0, 7.5, 0.5, 20.0, 0.25, -7.5)
        assert ds.GetProjection() and 'DERIVED' in ds.GetMetadataItem('SR_NOTICE')
        # A real model keeps the coarse content: each 4x4 block mean stays near its input pixel.
        small = out[0].reshape(size, 4, size, 4).mean(axis=(1, 3))
        error = float(np.abs(small - (base + ramp.astype(np.float64) * scale)).mean())
        assert error < 15 * scale, 'mean block error {:.2f}'.format(error)
        if alpha:
            assert (out[-1] == alpha).all()
        report = json.loads(Path(str(destination) + '.json').read_text(encoding='utf-8'))
        assert str(bundle) not in json.dumps(report)
        assert report['backend'] in ('CPU', 'DirectML GPU')
        if device == 'cpu':
            assert report['backend'] == 'CPU'
        if device == 'gpu':
            assert report['backend'] == 'DirectML GPU'
        print('{} passed on {} (mean block error {:.2f})'.format(name, report['backend'], error), flush=True)
        ds = None
app.exitQgis()
