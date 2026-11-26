"""Run real QGIS/GDAL/ONNX inference using an explicitly supplied runtime directory."""
import json
import os
from pathlib import Path
import sys
import tempfile

import numpy as np
from osgeo import gdal, osr
from qgis.core import QgsApplication

sys.path.insert(0, os.environ.get('LANDSAT_SR_TEST_PLUGIN_ROOT', str(Path(__file__).resolve().parents[1])))
from landsat_sr.plugin import RunTask
from landsat_sr.runtime_config import check_paths

bundle = Path(os.environ['LANDSAT_SR_RUNTIME_PACKAGE'])
device = os.environ.get('LANDSAT_SR_TEST_DEVICE', 'cpu')
python = bundle / 'runtime' / 'python.exe'
weights = bundle / 'weights'
assert check_paths(str(python), str(weights / 'real_hat_64.onnx')) == ''
app = QgsApplication([], False)
app.initQgis()
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    for mode, channels in [('rgb', 3), ('mono', 1)]:
        source = root / (mode + '_input.tif')
        destination = root / (mode + '_output.tif')
        ds = gdal.GetDriverByName('GTiff').Create(str(source), 8, 8, channels, gdal.GDT_Byte)
        ds.SetGeoTransform((10, 30, 0, 20, 0, -30))
        crs = osr.SpatialReference(); crs.ImportFromEPSG(32643); ds.SetProjection(crs.ExportToWkt())
        for i in range(channels):
            values = np.arange(64, dtype=np.uint8).reshape(8, 8) + 50 + i
            ds.GetRasterBand(i + 1).WriteArray(values)
        ds = None
        options = dict(source=str(source), output=str(destination), bands=[1, 2, 3], input_mode=mode,
                       auto_range=True, minimum=0, maximum=255, python=str(python),
                       weights=str(weights), model='real-hat-sharper', device=device, tile=64, add=False)
        task = RunTask(options, lambda *args: None)
        assert task.run(), task.error + '\n' + task.debug_traceback
        ds = gdal.Open(str(destination))
        assert (ds.RasterXSize, ds.RasterYSize, ds.RasterCount) == (32, 32, channels)
        assert ds.GetGeoTransform() == (10.0, 7.5, 0.0, 20.0, 0.0, -7.5)
        assert ds.GetProjection()
        assert ds.ReadAsArray().max() > 0
        report = json.loads(Path(str(destination) + '.json').read_text(encoding='utf-8'))
        assert report['backend'] in ('CPU', 'DirectML GPU')
        if device == 'cpu': assert report['backend'] == 'CPU'
        if device == 'gpu': assert report['backend'] == 'DirectML GPU'
        print('{} real-model inference passed on {}'.format(mode, report['backend']), flush=True)
        ds = None
app.exitQgis()
