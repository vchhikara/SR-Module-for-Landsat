# SPDX-License-Identifier: GPL-3.0-or-later
"""All GDAL access: local-only input, masks, georeferencing, output and read-back."""
import os
from pathlib import Path
from typing import Any
import zlib

import numpy as np
from osgeo import gdal

from .constants import NOTICE, SCALE, SRError

# Drivers that read local pixel data. VRT, WMS, WCS and other drivers that can
# point to other datasets or to the network are not in this list.
ALLOWED_DRIVERS = ['GTiff', 'HFA', 'ENVI', 'PNG', 'JPEG', 'JP2OpenJPEG', 'AAIGrid', 'BMP']
_REDIRECTS = (b'<VRTDataset', b'<GDAL_WMS', b'<WCS_GDAL', b'<GDALWMTS', b'OVERVIEW_FILE')
_TYPE_MAX = {gdal.GDT_Byte: 255, gdal.GDT_UInt16: 65535}
_EXPORT_HINT = ' Export the layer to a local GeoTIFF first.'


def _check_companion(path):
    """Refuse a sidecar that can make GDAL open another dataset."""
    with open(path, 'rb') as handle:
        head = handle.read(1024 * 1024)
    if any(marker in head for marker in _REDIRECTS):
        raise SRError('The sidecar file {} refers to another dataset.{}'.format(Path(path).name, _EXPORT_HINT))


def open_source(source):
    """Open a local raster file. Messages never repeat the source string, which can hold secrets."""
    text = str(source)
    if text.startswith(('/vsi', '\\vsi')) or '://' in text or not os.path.isfile(text):
        raise SRError('Only local raster files are accepted. Web services, database layers and '
                      'virtual paths are not supported.' + _EXPORT_HINT)
    parent = Path(text).resolve().parent
    name = Path(text).name.lower()
    stem = Path(text).stem.lower()
    companions = (name + '.msk', name + '.ovr', name + '.aux.xml', stem + '.aux')
    try:
        for item in parent.iterdir():
            if item.name.lower() in companions and item.is_file():
                _check_companion(item)
    except OSError as exc:
        raise SRError('Could not read the folder of the input raster: {}'.format(exc.strerror or exc)) from None
    try:
        dataset = gdal.OpenEx(text, gdal.OF_RASTER | gdal.OF_READONLY, allowed_drivers=ALLOWED_DRIVERS)
    except RuntimeError:
        dataset = None
    if dataset is None:
        raise SRError('GDAL could not open this file as a supported local raster ({}).{}'.format(
            ', '.join(ALLOWED_DRIVERS), _EXPORT_HINT))
    for item in dataset.GetFileList() or []:
        if item.startswith('/vsi') or '://' in item:
            raise SRError('The raster refers to remote or virtual data.' + _EXPORT_HINT)
    return dataset


class SourceSpec:
    """The validated plan for reading one source raster."""

    def __init__(self, dataset, mode, bands):
        self.dataset = dataset
        self.width, self.height = dataset.RasterXSize, dataset.RasterYSize
        if self.width <= 0 or self.height <= 0:
            raise SRError('Input raster is empty.')
        if mode not in ('auto', 'mono', 'rgb'):
            raise SRError('Unknown input mode.')
        interpretations = [dataset.GetRasterBand(i).GetColorInterpretation()
                           for i in range(1, dataset.RasterCount + 1)]
        alpha_indexes = [i for i, value in enumerate(interpretations, 1) if value == gdal.GCI_AlphaBand]
        if len(alpha_indexes) > 1:
            raise SRError('The raster has more than one alpha band.')
        self.mono = mode == 'mono' or (mode == 'auto' and dataset.RasterCount - len(alpha_indexes) == 1)
        self.indexes = list(bands[:1] if self.mono else bands[:3])
        if len(self.indexes) != (1 if self.mono else 3):
            raise SRError('Select one band for monochrome or three bands for RGB.')
        self.bands = []
        for index in self.indexes:
            if not 1 <= index <= dataset.RasterCount:
                raise SRError('Selected band {} does not exist.'.format(index))
            if index in alpha_indexes:
                raise SRError('Band {} is an alpha band. Select colour bands.'.format(index))
            band = dataset.GetRasterBand(index)
            if band.GetColorInterpretation() == gdal.GCI_PaletteIndex:
                raise SRError('Palette rasters hold class numbers. Convert the raster to RGB first.')
            self.bands.append(band)
        types = {band.DataType for band in self.bands}
        if len(types) != 1 or not types <= set(_TYPE_MAX):
            raise SRError('Select 8-bit or unsigned 16-bit bands of the same data type.')
        self.datatype = types.pop()
        self.dtype = np.uint8 if self.datatype == gdal.GDT_Byte else np.uint16
        self.type_max = _TYPE_MAX[self.datatype]

        self.alpha = dataset.GetRasterBand(alpha_indexes[0]) if alpha_indexes else None
        if self.alpha is not None and self.alpha.DataType not in _TYPE_MAX:
            raise SRError('The alpha band must be 8-bit or unsigned 16-bit.')
        self.masks = []  # (mask band, is_coverage)
        for band in self.bands:
            flags = band.GetMaskFlags()
            if flags & (gdal.GMF_ALL_VALID | gdal.GMF_ALPHA):
                continue  # the alpha band is read directly, at its full precision
            coverage = bool(flags & gdal.GMF_PER_DATASET) and not flags & gdal.GMF_NODATA
            self.masks.append((band.GetMaskBand(), coverage))
        self.has_transparency = self.alpha is not None or bool(self.masks)

    def read_rows(self, y, rows):
        """Return (values, coverage). values is (rows, width, n). coverage is 0..1, 0 means invalid."""
        arrays = [_read(band, y, self.width, rows) for band in self.bands]
        values = np.stack(arrays, axis=-1).astype(np.float32)
        coverage = np.ones((rows, self.width), np.float32)
        for mask, partial in self.masks:
            data = _read(mask, y, self.width, rows)
            part = data.astype(np.float32) / 255.0 if partial else (data != 0).astype(np.float32)
            coverage = np.minimum(coverage, part)
        if self.alpha is not None:
            data = _read(self.alpha, y, self.width, rows).astype(np.float32)
            coverage = np.minimum(coverage, data / _TYPE_MAX[self.alpha.DataType])
        return values, coverage


def _read(band, y, width, rows):
    data = band.ReadAsArray(0, y, width, rows)
    if data is None:
        raise SRError('Could not read the input raster.')
    return data


class Georeference:
    """Source georeferencing, already scaled to the 4x output grid."""

    def __init__(self, dataset):
        if dataset.GetMetadata('GEOLOCATION'):
            raise SRError('This raster uses geolocation arrays. Warp it to a regular grid first.')
        transform = dataset.GetGeoTransform(can_return_null=True)
        self.transform = None
        if transform is not None:
            self.transform = (transform[0], transform[1] / SCALE, transform[2] / SCALE,
                              transform[3], transform[4] / SCALE, transform[5] / SCALE)
        self.gcps = []
        if self.transform is None:
            # GCP pixel and line count from the top-left corner, so they scale directly.
            self.gcps = [gdal.GCP(g.GCPX, g.GCPY, g.GCPZ, g.GCPPixel * SCALE, g.GCPLine * SCALE, g.Info, g.Id)
                         for g in dataset.GetGCPs()]
        self.projection = (dataset.GetGCPProjection() if self.gcps else dataset.GetProjection()) or ''
        self.srs = dataset.GetGCPSpatialRef() if self.gcps else dataset.GetSpatialRef()
        self.rpc = dict(dataset.GetMetadata('RPC') or {})
        if self.rpc:
            try:
                for axis in ('LINE', 'SAMP'):
                    # RPC offsets use pixel centres: centre c maps to SCALE * (c + 0.5) - 0.5.
                    offset = float(self.rpc[axis + '_OFF'].split()[0])
                    self.rpc[axis + '_OFF'] = repr(SCALE * offset + (SCALE - 1) / 2)
                    self.rpc[axis + '_SCALE'] = repr(SCALE * float(self.rpc[axis + '_SCALE'].split()[0]))
            except (KeyError, ValueError, IndexError):
                raise SRError('The RPC georeferencing of this raster is incomplete.') from None
        self.area_or_point = dataset.GetMetadataItem('AREA_OR_POINT')

    @property
    def kind(self):
        kinds = [name for name, present in (('affine', self.transform), ('gcp', self.gcps), ('rpc', self.rpc))
                 if present]
        return '+'.join(kinds) or 'none'

    def apply(self, out):
        if self.area_or_point:  # set first: GDAL uses it to encode the coordinates
            # GDAL reports GCPs in the pixel-is-area convention, but it does not round-trip them
            # in a GeoTIFF tagged 'Point' (they move by one pixel). Keep the tag as plain metadata.
            key = 'SR_SOURCE_AREA_OR_POINT' if self.gcps else 'AREA_OR_POINT'
            _check(out.SetMetadataItem(key, self.area_or_point))
        if self.transform is not None:
            _check(out.SetGeoTransform(self.transform))
        if self.gcps:
            _check(out.SetGCPs(self.gcps, self.projection))
        elif self.projection:
            _check(out.SetProjection(self.projection))
        if self.rpc:
            _check(out.SetMetadata(self.rpc, 'RPC'))

    def verify(self, out):
        """Raise if the stored GeoTIFF does not carry the planned georeferencing."""
        def fail(what):
            raise SRError('The GeoTIFF did not store the {} exactly. Reproject the input first.'.format(what))
        if self.transform is not None:
            stored = out.GetGeoTransform(can_return_null=True)
            if stored is None or not np.allclose(stored, self.transform, rtol=1e-12, atol=1e-9):
                fail('geotransform')
        if self.gcps:
            stored = out.GetGCPs()
            if len(stored) != len(self.gcps) or any(
                    not np.allclose((a.GCPPixel, a.GCPLine, a.GCPX, a.GCPY, a.GCPZ),
                                    (b.GCPPixel, b.GCPLine, b.GCPX, b.GCPY, b.GCPZ), rtol=1e-12, atol=1e-6)
                    for a, b in zip(stored, self.gcps)):
                fail('ground control points')
        if self.srs is not None:
            stored = out.GetGCPSpatialRef() if self.gcps else out.GetSpatialRef()
            if stored is None or not stored.IsSame(self.srs, ['IGNORE_DATA_AXIS_TO_SRS_AXIS_MAPPING=YES']):
                fail('coordinate reference system')
        if self.rpc:
            stored = out.GetMetadata('RPC') or {}
            for key in ('LINE_OFF', 'SAMP_OFF', 'LINE_SCALE', 'SAMP_SCALE'):
                if key not in stored or not np.isclose(float(stored[key].split()[0]), float(self.rpc[key])):
                    fail('RPC model')


def _check(code):
    if code not in (None, gdal.CE_None):
        raise SRError('GDAL reported a write error: {}'.format(gdal.GetLastErrorMsg() or code))


class OutputRaster:
    """A staging GeoTIFF that records a checksum of every strip for read-back."""

    def __init__(self, path, spec, georeference, metadata):
        self.path = str(path)
        self.georeference = georeference
        self.width, self.height = spec.width * SCALE, spec.height * SCALE
        data_bands = 1 if spec.mono else 3
        self.count = data_bands + (1 if spec.has_transparency else 0)
        self.errors: list = []
        self.strips: list = []
        self._open = True
        self._pam = gdal.GetThreadLocalConfigOption('GDAL_PAM_ENABLED')
        # Without PAM, everything must be stored inside the TIFF itself.
        gdal.SetThreadLocalConfigOption('GDAL_PAM_ENABLED', 'NO')
        gdal.PushErrorHandler(self._on_error)
        self.dataset: Any = None
        try:
            options = ['COMPRESS=DEFLATE', 'TILED=YES', 'BIGTIFF=IF_SAFER',
                       'PHOTOMETRIC=' + ('MINISBLACK' if spec.mono else 'RGB')]
            if spec.has_transparency:
                options.append('ALPHA=YES')
            self.dataset = gdal.GetDriverByName('GTiff').Create(
                self.path, self.width, self.height, self.count, spec.datatype, options=options)
            if self.dataset is None:
                raise SRError('Could not create the output GeoTIFF: ' + gdal.GetLastErrorMsg())
            georeference.apply(self.dataset)
            colours = ((gdal.GCI_GrayIndex,) if spec.mono
                       else (gdal.GCI_RedBand, gdal.GCI_GreenBand, gdal.GCI_BlueBand))
            if spec.has_transparency:
                colours += (gdal.GCI_AlphaBand,)
            for number, colour in enumerate(colours, 1):
                band = self.dataset.GetRasterBand(number)
                _check(band.SetColorInterpretation(colour))
                if colour != gdal.GCI_AlphaBand:
                    band.SetDescription('Derived visualization, not measured data')
            for key, value in metadata.items():
                _check(self.dataset.SetMetadataItem(key, str(value)))
        except BaseException:
            self.close()
            raise

    def _on_error(self, level, number, message):
        if level >= gdal.CE_Failure:
            self.errors.append(message)

    def write(self, y, planes):
        """Write one full-width strip. planes is a list of (rows, width) arrays, one per band."""
        sums = []
        for number, plane in enumerate(planes, 1):
            plane = np.ascontiguousarray(plane)
            _check(self.dataset.GetRasterBand(number).WriteArray(plane, 0, y))
            sums.append(zlib.crc32(plane.tobytes()))
        self.strips.append((y, planes[0].shape[0], sums))
        self._raise_errors()

    def _raise_errors(self):
        if self.errors:
            raise SRError('GDAL could not write the output: ' + self.errors[0])

    def finish(self):
        """Flush, close, then reopen the file and compare every strip and the georeferencing."""
        try:
            _check(self.dataset.FlushCache())
            if hasattr(self.dataset, 'Close'):  # GDAL 3.8+ returns close errors
                _check(self.dataset.Close())
            self.dataset = None
            self._raise_errors()
            self._verify()
        finally:
            self.close()

    def _verify(self):
        failure = None
        try:
            self._compare()
        except Exception as exc:
            # Keep only the text. A kept traceback would hold the file open, and
            # Windows could then not delete the staging folder.
            failure = str(exc)
        if failure is not None:
            raise SRError(failure)
        self._raise_errors()

    def _compare(self):
        stored = gdal.OpenEx(self.path, gdal.OF_RASTER | gdal.OF_READONLY, allowed_drivers=['GTiff'])
        if stored is None or (stored.RasterXSize, stored.RasterYSize, stored.RasterCount) != (
                self.width, self.height, self.count):
            raise SRError('The written GeoTIFF is incomplete.')
        self.georeference.verify(stored)
        for y, rows, sums in self.strips:
            for number, expected in enumerate(sums, 1):
                data = stored.GetRasterBand(number).ReadAsArray(0, y, self.width, rows)
                if data is None or zlib.crc32(np.ascontiguousarray(data).tobytes()) != expected:
                    raise SRError('The written GeoTIFF failed read-back verification.')

    def close(self):
        """Release GDAL state. Safe to call twice."""
        if not self._open:
            return
        self.dataset = None
        gdal.PopErrorHandler()
        gdal.SetThreadLocalConfigOption('GDAL_PAM_ENABLED', self._pam)
        self._open = False


def output_metadata(extra):
    base = {'SR_NOTICE': NOTICE, 'TIFFTAG_IMAGEDESCRIPTION': NOTICE, 'SR_SCALE': SCALE}
    base.update(extra)
    return base
