"""The full pipeline on native GDAL with an exact fake model."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pytest

gdal = pytest.importorskip('osgeo.gdal')
from osgeo import osr  # noqa: E402

from conftest import FakePredictor, nearest4  # noqa: E402
from landsat_sr import engine, publish, raster, tiling  # noqa: E402
from landsat_sr.constants import Cancelled, SRError  # noqa: E402

RNG = np.random.default_rng(7)


def wgs84():
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def make(path, data, dtype=gdal.GDT_Byte, options=(), transform=(10, 30, 0, 20, 0, -30), epsg=32643,
         setup=None):
    count, height, width = data.shape
    ds = gdal.GetDriverByName('GTiff').Create(str(path), width, height, count, dtype, options=list(options))
    if transform:
        ds.SetGeoTransform(transform)
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(epsg)
        ds.SetProjection(srs.ExportToWkt())
    for i in range(count):
        ds.GetRasterBand(i + 1).WriteArray(data[i])
    if setup:
        setup(ds)
    ds = None
    return str(path)


def pixels(path):
    ds = gdal.Open(str(path))
    data = ds.ReadAsArray()
    ds = None
    return data if data.ndim == 3 else data[None]


def run(tmp_path, source, predictor=None, name='out.tif', **extra):
    options = dict(source=source, output=str(tmp_path / name), bands=[1, 2, 3], input_mode='auto',
                   auto_range=True, device='cpu')
    options.update(extra)
    return engine.run_job(options, predictor or FakePredictor()), tmp_path / name


def upscaled(data):
    return np.repeat(np.repeat(data, 4, axis=1), 4, axis=2)


def assert_nothing_published(tmp_path, name='out.tif'):
    assert not (tmp_path / name).exists()
    assert not (tmp_path / (name + '.json')).exists()
    assert not [p for p in tmp_path.iterdir() if p.name.startswith('.qgis_sr_')]


def small(tmp_path, bands=1, size=8):
    return make(tmp_path / 'in.tif', RNG.integers(1, 255, (bands, size, size), np.uint8))


# ---- exact pixels -----------------------------------------------------------

@pytest.mark.parametrize('width,height', [(1, 1), (1, 70), (70, 1), (63, 65), (64, 64), (112, 113),
                                          (193, 191), (225, 224), (257, 577), (577, 257)])
def test_rgb_pixels_are_exact(tmp_path, width, height):
    data = RNG.integers(0, 256, (3, height, width), np.uint8)
    _, out = run(tmp_path, make(tmp_path / 'in.tif', data))
    np.testing.assert_array_equal(pixels(out), upscaled(data))


@pytest.mark.parametrize('bands', [1, 3])
def test_uint16_pixels_are_exact(tmp_path, bands):
    data = RNG.integers(0, 65536, (bands, 100, 130), np.uint16)
    report, out = run(tmp_path, make(tmp_path / 'in.tif', data, gdal.GDT_UInt16))
    result = pixels(out)
    assert result.dtype == np.uint16 and report['output_bit_depth'] == 16
    assert np.abs(result.astype(int) - upscaled(data).astype(int)).max() <= 1


class PositionModel:
    """Output depends on the position inside the tile, as a real network's context does."""

    def __init__(self):
        ramp = np.linspace(-0.2, 0.2, 256, dtype=np.float32)
        self.bias = ramp[None, :, None, None] + ramp[None, None, :, None] ** 2

    def __call__(self, batch):
        return np.clip(nearest4(batch) + self.bias, 0, 1).astype(np.float32)


def full_image_reference(image, model):
    """Every tile of the whole image, blended in one buffer. No streaming."""
    height, width = image.shape[:2]
    ys, wy = tiling.axis_weights(height)
    xs, wx = tiling.axis_weights(width)
    out = np.zeros((height * 4, width * 4, 3), np.float32)
    for row, y in enumerate(ys):
        for col, x in enumerate(xs):
            patch = image[y:y + 64, x:x + 64]
            h, w = patch.shape[:2]
            tile = model(tiling.pad_tile(patch)[None])[0, :h * 4, :w * 4]
            out[y * 4:(y + h) * 4, x * 4:(x + w) * 4] += tile * (wy[row][:, None, None] * wx[col][None, :, None])
    return np.clip(out, 0, 1)


@pytest.mark.parametrize('width,height', [(193, 191), (257, 577), (400, 60)])
def test_streaming_equals_one_full_image_pass(tmp_path, width, height):
    data = RNG.integers(0, 256, (3, height, width), np.uint8)
    model = PositionModel()
    _, out = run(tmp_path, make(tmp_path / 'in.tif', data), FakePredictor(model))
    expected = full_image_reference(data.transpose(1, 2, 0).astype(np.float32) / 255, model)
    expected = (expected * 255).round().transpose(2, 0, 1)
    assert np.abs(pixels(out).astype(float) - expected).max() <= 1


# ---- H-02 broken model output -------------------------------------------------

@pytest.mark.parametrize('change', [
    lambda b: np.full_like(nearest4(b), np.nan),
    lambda b: np.full_like(nearest4(b), np.inf),
    lambda b: nearest4(b) + 1000,
    lambda b: nearest4(b)[..., :1],
    lambda b: nearest4(b).astype(np.float64),
], ids=['nan', 'inf', 'huge', 'shape', 'dtype'])
def test_broken_model_output_publishes_nothing(tmp_path, change):
    with pytest.raises(SRError, match='model returned'):
        run(tmp_path, small(tmp_path), FakePredictor(change))
    assert_nothing_published(tmp_path)


# ---- H-04 alpha and masks ------------------------------------------------------

@pytest.mark.parametrize('bands,dtype,gdt,value', [
    (4, np.uint8, gdal.GDT_Byte, 127), (2, np.uint8, gdal.GDT_Byte, 127),
    (4, np.uint16, gdal.GDT_UInt16, 32767)])
def test_partial_alpha_survives(tmp_path, bands, dtype, gdt, value):
    data = np.full((bands, 80, 90), 100, dtype)
    data[-1] = value
    data[-1, :10, :10] = 0
    data[-1, 20:30, 20:30] = 1
    photometric = 'RGB' if bands == 4 else 'MINISBLACK'
    source = make(tmp_path / 'in.tif', data, gdt, ['PHOTOMETRIC=' + photometric, 'ALPHA=YES'])
    report, out = run(tmp_path, source)
    np.testing.assert_array_equal(pixels(out)[-1], upscaled(data[-1:])[0])
    assert report['invalid_input_pixels'] == 100
    assert gdal.Open(str(out)).GetRasterBand(bands).GetColorInterpretation() == gdal.GCI_AlphaBand


def test_per_band_nodata_is_combined(tmp_path):
    # HFA stores one NoData value per band. GeoTIFF stores only one per file.
    source = str(tmp_path / 'in.img')
    ds = gdal.GetDriverByName('HFA').Create(source, 20, 20, 3, gdal.GDT_Byte)
    for i, value in enumerate([1, 2, 3]):
        array = np.full((20, 20), 50, np.uint8)
        array[i, i] = value
        ds.GetRasterBand(i + 1).SetNoDataValue(value)
        ds.GetRasterBand(i + 1).WriteArray(array)
    ds = None
    report, out = run(tmp_path, source)
    alpha = pixels(out)[3]
    assert report['invalid_input_pixels'] == 3
    assert all(alpha[i * 4, i * 4] == 0 for i in range(3)) and alpha[40, 40] == 255


def test_internal_mask_becomes_alpha(tmp_path):
    def setup(ds):
        ds.CreateMaskBand(gdal.GMF_PER_DATASET)
        mask = np.full((16, 16), 255, np.uint8)
        mask[:4] = 0
        ds.GetRasterBand(1).GetMaskBand().WriteArray(mask)
    source = make(tmp_path / 'in.tif', np.full((1, 16, 16), 9, np.uint8), setup=setup)
    report, out = run(tmp_path, source)
    assert report['invalid_input_pixels'] == 64
    assert pixels(out)[1][0, 0] == 0 and pixels(out)[1][-1, -1] == 255


def test_empty_tiles_need_no_inference(tmp_path):
    data = np.zeros((1, 64, 400), np.uint8)
    data[0, :, :10] = 200
    source = make(tmp_path / 'in.tif', data, setup=lambda ds: ds.GetRasterBand(1).SetNoDataValue(0))
    report, out = run(tmp_path, source)
    assert report['tiles_predicted'] == 1
    np.testing.assert_array_equal(pixels(out)[0], upscaled(data)[0])


def test_alpha_and_palette_selections_are_refused(tmp_path):
    source = make(tmp_path / 'in.tif', np.full((4, 8, 8), 100, np.uint8),
                  options=['PHOTOMETRIC=RGB', 'ALPHA=YES'])
    with pytest.raises(SRError, match='alpha band'):
        run(tmp_path, source, bands=[1, 2, 4], input_mode='rgb')

    def palette(ds):
        table = gdal.ColorTable()
        table.SetColorEntry(0, (0, 0, 0, 255))
        ds.GetRasterBand(1).SetColorTable(table)
    source = make(tmp_path / 'p.tif', np.zeros((1, 8, 8), np.uint8), setup=palette)
    with pytest.raises(SRError, match='Palette'):
        run(tmp_path, source)


def test_display_range_is_enforced(tmp_path):
    with pytest.raises(SRError, match='outside the selected display range'):
        run(tmp_path, small(tmp_path), auto_range=False, minimum=100, maximum=101)
    with pytest.raises(SRError, match='must exceed'):
        run(tmp_path, small(tmp_path), auto_range=False, minimum=5, maximum=float('nan'))
    assert_nothing_published(tmp_path)


# ---- H-03 and M-11 georeferencing and metadata ---------------------------------

@pytest.mark.parametrize('transform', [(10, 30, 0, 20, 0, -30), (10, 3, 1.5, 20, 0.5, -3)])
def test_affine_transform_keeps_the_extent(tmp_path, transform):
    source = make(tmp_path / 'in.tif', np.ones((1, 8, 8), np.uint8), transform=transform)
    _, out = run(tmp_path, source)
    t = transform
    assert gdal.Open(str(out)).GetGeoTransform() == pytest.approx(
        (t[0], t[1] / 4, t[2] / 4, t[3], t[4] / 4, t[5] / 4))


@pytest.mark.parametrize('point', [False, True])
def test_ground_control_points_are_scaled(tmp_path, point):
    gcps = [gdal.GCP(10, 20, 0, 0, 0), gdal.GCP(11, 20, 0, 8, 0), gdal.GCP(10, 19, 0, 0, 8)]

    def setup(ds):
        if point:
            ds.SetMetadataItem('AREA_OR_POINT', 'Point')
        ds.SetGCPs(gcps, wgs84().ExportToWkt())
    source = make(tmp_path / 'in.tif', np.ones((1, 8, 8), np.uint8), transform=None, setup=setup)
    before = gdal.Open(source)
    expected = [(g.GCPPixel * 4, g.GCPLine * 4, g.GCPX, g.GCPY) for g in before.GetGCPs()]
    report, out = run(tmp_path, source)
    ds = gdal.Open(str(out))
    np.testing.assert_allclose([(g.GCPPixel, g.GCPLine, g.GCPX, g.GCPY) for g in ds.GetGCPs()], expected)
    assert ds.GetGCPSpatialRef().GetAuthorityCode(None) == '4326'
    assert report['georeference'] == 'gcp'
    if point:
        assert ds.GetMetadataItem('SR_SOURCE_AREA_OR_POINT') == 'Point'


def test_pixel_is_point_keeps_the_geotransform(tmp_path):
    source = make(tmp_path / 'in.tif', np.ones((1, 8, 8), np.uint8),
                  setup=lambda ds: ds.SetMetadataItem('AREA_OR_POINT', 'Point'))
    original = gdal.Open(source).GetGeoTransform()
    _, out = run(tmp_path, source)
    ds = gdal.Open(str(out))
    assert ds.GetMetadataItem('AREA_OR_POINT') == 'Point'
    assert ds.GetGeoTransform() == pytest.approx(
        (original[0], original[1] / 4, 0, original[3], 0, original[5] / 4))


def rpc_metadata():
    zero = ['0'] * 20

    def terms(index):
        values = list(zero)
        values[index] = '1'
        return ' '.join(values)
    return {'LINE_OFF': '50', 'SAMP_OFF': '60', 'LAT_OFF': '20', 'LONG_OFF': '77', 'HEIGHT_OFF': '0',
            'LINE_SCALE': '50', 'SAMP_SCALE': '60', 'LAT_SCALE': '1', 'LONG_SCALE': '1', 'HEIGHT_SCALE': '1',
            'LINE_NUM_COEFF': terms(2), 'LINE_DEN_COEFF': terms(0),
            'SAMP_NUM_COEFF': terms(1), 'SAMP_DEN_COEFF': terms(0)}


def test_rpc_maps_ground_points_to_four_times_the_pixel(tmp_path):
    source = make(tmp_path / 'in.tif', np.ones((1, 100, 120), np.uint8), transform=None,
                  setup=lambda ds: ds.SetMetadata(rpc_metadata(), 'RPC'))
    report, out = run(tmp_path, source)
    assert report['georeference'] == 'rpc'
    for lon, lat in [(77.0, 20.0), (76.4, 20.3), (77.5, 19.6)]:
        found = []
        for path in (source, str(out)):
            ds = gdal.Open(path)
            ok, point = gdal.Transformer(ds, None, ['METHOD=RPC']).TransformPoint(1, lon, lat, 0)
            assert ok
            found.append(np.array(point[:2]))
        np.testing.assert_allclose(found[1], found[0] * 4, atol=1e-6)


def test_geolocation_arrays_are_refused(tmp_path):
    source = make(tmp_path / 'in.tif', np.ones((1, 8, 8), np.uint8),
                  setup=lambda ds: ds.SetMetadata({'X_DATASET': 'x.tif'}, 'GEOLOCATION'))
    with pytest.raises(SRError, match='geolocation arrays'):
        run(tmp_path, source)


def test_the_tiff_alone_says_that_it_is_derived(tmp_path):
    report, out = run(tmp_path, small(tmp_path))
    os.unlink(str(out) + '.json')
    ds = gdal.Open(str(out))
    meta = ds.GetMetadata()
    for key in ('TIFFTAG_IMAGEDESCRIPTION', 'SR_NOTICE'):
        assert 'DERIVED VISUALIZATION' in meta[key]
    assert meta['SR_SCALE'] == '4' and meta['SR_SOURCE_NAME'] == 'in.tif'
    assert meta['SR_MODEL_SHA256'] == report['model_sha256']
    assert 'Derived' in ds.GetRasterBand(1).GetDescription()
    assert sorted(p.name for p in tmp_path.iterdir()) == ['in.tif', 'out.tif']  # no sidecar


# ---- H-01 report contents -------------------------------------------------------

def test_report_has_no_paths_and_no_option_passthrough(tmp_path):
    report, out = run(tmp_path, small(tmp_path), python='/secret/runtime/python.exe',
                      model_path='/secret/model', password='hunter2')
    text = (tmp_path / 'out.tif.json').read_text()
    assert 'hunter2' not in text and '/secret' not in text and str(tmp_path) not in text
    assert json.loads(text) == report
    assert report['source_name'] == 'in.tif' and report['output_name'] == 'out.tif'


# ---- M-05 local input only --------------------------------------------------------

def test_remote_virtual_and_provider_sources_are_refused_without_requests(tmp_path):
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_error(404)
        do_HEAD = do_GET

        def log_message(self, *args):
            pass
    server = HTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = 'http://127.0.0.1:{}/a.tif'.format(server.server_port)
    local = small(tmp_path)
    vrt = tmp_path / 'remote.vrt'
    template = ('<VRTDataset rasterXSize="8" rasterYSize="8"><VRTRasterBand dataType="Byte" band="1">'
                '<SimpleSource><SourceFilename>/vsicurl/{}</SourceFilename></SimpleSource>'
                '</VRTRasterBand></VRTDataset>').format(url)
    vrt.write_text(template)
    disguised = tmp_path / 'disguised.tif'
    disguised.write_text(template)
    masked = tmp_path / 'masked.tif'
    masked.write_bytes(open(local, 'rb').read())
    (tmp_path / 'masked.tif.msk').write_text(template)
    try:
        for source in (url, '/vsicurl/' + url, 'user:secret@' + url, str(vrt), str(disguised), str(masked),
                       'dbname=x password=secret table=y', 'GPKG:/a.gpkg:layer'):
            with pytest.raises(SRError) as caught:
                run(tmp_path, source)
            assert 'secret' not in str(caught.value)
    finally:
        server.shutdown()
    assert hits == []
    assert_nothing_published(tmp_path)


def local_vrt(target):
    return ('<VRTDataset rasterXSize="8" rasterYSize="8"><VRTRasterBand dataType="Byte" band="1">'
            '<SimpleSource><SourceFilename>{}</SourceFilename></SimpleSource>'
            '</VRTRasterBand></VRTDataset>').format(target)


@pytest.mark.parametrize('name', ['stack.vrt', 'disguised.tif'])
def test_even_a_local_only_vrt_is_refused(tmp_path, name):
    """Only the driver allowlist can refuse this input: every file it refers to is local."""
    target = small(tmp_path)
    (tmp_path / name).write_text(local_vrt(target))
    with pytest.raises(SRError, match='could not open this file as a supported local raster'):
        run(tmp_path, str(tmp_path / name))


@pytest.mark.parametrize('suffix,content', [
    ('.msk', None), ('.ovr', None),
    ('.aux.xml', '<PAMDataset><Metadata domain="OVERVIEWS"><MDI key="OVERVIEW_FILE">x.tif</MDI>'
                 '</Metadata></PAMDataset>')])
def test_a_sidecar_that_redirects_gdal_is_refused(tmp_path, suffix, content):
    source = small(tmp_path)
    (tmp_path / ('in.tif' + suffix)).write_text(content or local_vrt(source))
    with pytest.raises(SRError, match='refers to another dataset'):
        run(tmp_path, source)
    assert_nothing_published(tmp_path)


# ---- H-05 durability ---------------------------------------------------------------

def test_flush_error_code_blocks_publication(tmp_path, monkeypatch):
    real = raster.OutputRaster.finish

    class Failing:
        def __init__(self, ds):
            self.ds = ds

        def FlushCache(self):
            self.ds.FlushCache()
            return gdal.CE_Failure

    def finish(self):
        self.dataset = Failing(self.dataset)
        real(self)
    monkeypatch.setattr(raster.OutputRaster, 'finish', finish)
    with pytest.raises(SRError, match='write error'):
        run(tmp_path, small(tmp_path))
    assert_nothing_published(tmp_path)


def test_silent_corruption_is_found_by_read_back(tmp_path, monkeypatch):
    real = raster.OutputRaster._verify

    def corrupt_then_verify(self):
        ds = gdal.Open(self.path, gdal.GA_Update)
        ds.GetRasterBand(1).WriteArray(np.zeros((1, 1), np.uint8), 3, 3)
        ds = None
        real(self)
    monkeypatch.setattr(raster.OutputRaster, '_verify', corrupt_then_verify)
    with pytest.raises(SRError, match='read-back'):
        run(tmp_path, small(tmp_path))
    assert_nothing_published(tmp_path)


def test_truncated_staging_file_is_refused(tmp_path, monkeypatch):
    real = raster.OutputRaster._verify

    def truncate_then_verify(self):
        os.truncate(self.path, os.path.getsize(self.path) // 2)
        real(self)
    monkeypatch.setattr(raster.OutputRaster, '_verify', truncate_then_verify)
    with pytest.raises((SRError, RuntimeError)):
        run(tmp_path, small(tmp_path, size=200))
    assert_nothing_published(tmp_path)


@pytest.mark.skipif(not os.path.isdir('/proc/self/fd'), reason='reads open handles from /proc')
@pytest.mark.parametrize('error', [SRError, RuntimeError], ids=['sr', 'gdal'])
def test_a_failed_read_back_releases_the_staging_file(tmp_path, monkeypatch, error):
    """Windows cannot delete an open file, so cleanup must start with no handle into the staging folder."""
    held = []
    real = publish.shutil.rmtree

    def spy(path, **kwargs):
        for number in os.listdir('/proc/self/fd'):
            try:
                target = os.readlink('/proc/self/fd/' + number)
            except OSError:
                continue
            if target.startswith(str(path)):
                held.append(os.path.basename(target))
        real(path, **kwargs)

    def fail(self, stored):
        raise error('forced')  # a new object each time, as GDAL does
    monkeypatch.setattr(publish.shutil, 'rmtree', spy)
    monkeypatch.setattr(raster.Georeference, 'verify', fail)
    with pytest.raises(SRError, match='forced'):
        run(tmp_path, small(tmp_path))
    assert held == []
    assert_nothing_published(tmp_path)


@pytest.mark.skipif(os.name == 'nt' or os.geteuid() == 0, reason='needs POSIX permissions')
def test_an_unlistable_input_folder_gives_a_clear_message(tmp_path):
    folder = tmp_path / 'locked'
    folder.mkdir()
    source = small(folder)
    folder.chmod(0o111)
    try:
        with pytest.raises(SRError, match='folder of the input'):
            run(tmp_path, source)
    finally:
        folder.chmod(0o755)


def test_an_unwritable_output_folder_fails_at_once_with_a_message(tmp_path, monkeypatch):
    """On Windows, tempfile.mkdtemp retries about 2**31 times when the folder ACL denies new folders."""
    source = small(tmp_path)
    real = os.mkdir
    attempts = []

    def deny(path, *args, **kwargs):
        if os.path.basename(path).startswith('.qgis_sr_'):
            attempts.append(path)
            assert len(attempts) <= 20, 'the staging folder is retried without a limit'
            raise PermissionError(13, 'Access is denied', str(path))
        return real(path, *args, **kwargs)
    monkeypatch.setattr(os, 'mkdir', deny)
    with pytest.raises(SRError, match='output folder'):
        run(tmp_path, source)
    assert_nothing_published(tmp_path)


def coarse_model(batch):
    """Like a real model, it has an error of fixed size on its 0..1 scale: it keeps only 64 levels."""
    return nearest4(np.round(batch * 64) / 64).astype(np.float32)


def test_low_contrast_16_bit_data_keeps_its_detail(tmp_path):
    """Landsat land pixels use a few percent of 0..65535. The model must still see their contrast."""
    data = RNG.integers(7000, 10000, (3, 100, 130), np.uint16)
    source = make(tmp_path / 'in.tif', data, gdal.GDT_UInt16)
    _, out = run(tmp_path, source, FakePredictor(coarse_model))
    error = np.abs(pixels(out).astype(np.int32) - upscaled(data).astype(np.int32))
    assert error.mean() < 50  # one level of 64 over 0..65535 is 1024 DN


def test_the_model_input_uses_the_contrast_of_each_16_bit_tile(tmp_path):
    seen = []

    def record(batch):
        seen.extend((float(tile.min()), float(tile.max())) for tile in batch)
        return nearest4(batch)
    data = RNG.integers(7000, 10000, (3, 64, 64), np.uint16)
    run(tmp_path, make(tmp_path / 'in.tif', data, gdal.GDT_UInt16), FakePredictor(record))
    low, high = seen[0]
    assert -1e-6 <= low < 0.3 and 0.7 < high <= 1 + 1e-6


def test_a_flat_16_bit_area_is_not_stretched_into_noise(tmp_path):
    seen = []

    def record(batch):
        seen.extend(float(np.ptp(tile)) for tile in batch)
        return nearest4(batch)
    data = RNG.integers(8000, 8004, (3, 64, 64), np.uint16)
    _, out = run(tmp_path, make(tmp_path / 'in.tif', data, gdal.GDT_UInt16), FakePredictor(record))
    assert seen[0] < 0.1
    np.testing.assert_array_equal(pixels(out), upscaled(data))


def test_no_data_pixels_do_not_enter_the_model_as_black(tmp_path):
    seen = []

    def record(batch):
        seen.extend(batch.copy())
        return nearest4(batch)
    data = RNG.integers(7000, 10000, (3, 64, 64), np.uint16)
    data[:, :, :20] = 0
    source = make(tmp_path / 'in.tif', data, gdal.GDT_UInt16,
                  setup=lambda ds: [ds.GetRasterBand(i).SetNoDataValue(0) for i in (1, 2, 3)])
    run(tmp_path, source, FakePredictor(record))
    tile = seen[0]
    expected = np.broadcast_to(tile[:, 20:].mean(axis=(0, 1)), tile[:, :20].shape)
    np.testing.assert_allclose(tile[:, :20], expected, atol=1e-3)


def test_data_that_uses_few_bits_of_a_16_bit_file_keeps_its_detail(tmp_path):
    """Some sensors store 8 to 11 bit values in UInt16, for example 60 to 170."""
    seen = []

    def record(batch):
        seen.extend(float(tile.max()) for tile in batch)
        return coarse_model(batch)
    data = RNG.integers(60, 171, (3, 100, 130), np.uint16)
    _, out = run(tmp_path, make(tmp_path / 'in.tif', data, gdal.GDT_UInt16), FakePredictor(record))
    assert min(seen) > 0.7
    error = np.abs(pixels(out).astype(np.int32) - upscaled(data).astype(np.int32))
    assert error.mean() < 2


def test_a_flat_area_with_small_values_is_not_stretched_into_noise(tmp_path):
    seen = []

    def record(batch):
        seen.extend(float(np.ptp(tile)) for tile in batch)
        return nearest4(batch)
    data = RNG.integers(60, 64, (3, 64, 64), np.uint16)
    _, out = run(tmp_path, make(tmp_path / 'in.tif', data, gdal.GDT_UInt16), FakePredictor(record))
    assert seen[0] < 0.1
    np.testing.assert_array_equal(pixels(out), upscaled(data))


def test_gdal_configuration_is_restored(tmp_path):
    gdal.SetThreadLocalConfigOption('GDAL_PAM_ENABLED', None)
    run(tmp_path, small(tmp_path))
    with pytest.raises(SRError):
        run(tmp_path, small(tmp_path), FakePredictor(lambda b: nearest4(b) * np.nan), name='bad.tif')
    assert gdal.GetThreadLocalConfigOption('GDAL_PAM_ENABLED') is None


# ---- H-06 and M-01 publication -------------------------------------------------------

@pytest.mark.parametrize('victim', ['out.tif', 'out.tif.json'])
def test_a_file_created_in_the_race_window_is_kept(tmp_path, monkeypatch, victim):
    real = publish.move_no_clobber

    def interpose(source, target):
        if os.path.basename(target) == victim:
            with open(target, 'wb') as handle:
                handle.write(b'SENTINEL')
        real(source, target)
    monkeypatch.setattr(publish, 'move_no_clobber', interpose)
    with pytest.raises(SRError, match='No file was replaced'):
        run(tmp_path, small(tmp_path))
    assert (tmp_path / victim).read_bytes() == b'SENTINEL'
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(['in.tif', victim])


def test_failed_tiff_publication_removes_our_report(tmp_path, monkeypatch):
    real = publish.move_no_clobber

    def fail_tiff(source, target):
        if str(target).endswith('.tif'):
            raise OSError('injected')
        real(source, target)
    monkeypatch.setattr(publish, 'move_no_clobber', fail_tiff)
    with pytest.raises(OSError, match='injected'):
        run(tmp_path, small(tmp_path))
    assert_nothing_published(tmp_path)


def test_no_hard_link_file_system_still_never_clobbers(tmp_path, monkeypatch):
    def no_link(*args):
        raise PermissionError('hard links not supported')
    monkeypatch.setattr(publish.os, 'link', no_link)
    (tmp_path / 'a').write_bytes(b'new')
    (tmp_path / 'b').write_bytes(b'old')
    with pytest.raises(FileExistsError):
        publish.move_no_clobber(tmp_path / 'a', tmp_path / 'b')
    assert (tmp_path / 'b').read_bytes() == b'old'
    publish.move_no_clobber(tmp_path / 'a', tmp_path / 'c')
    assert (tmp_path / 'c').read_bytes() == b'new' and not (tmp_path / 'a').exists()


@pytest.mark.parametrize('existing', ['out.tif', 'out.tif.json', 'out.tif.aux.xml', 'out.tif.msk', 'out.tfw'])
def test_existing_files_and_stale_sidecars_block_the_run(tmp_path, existing):
    source = small(tmp_path)
    (tmp_path / existing).write_bytes(b'keep')
    with pytest.raises(SRError, match='already exist'):
        run(tmp_path, source)
    assert (tmp_path / existing).read_bytes() == b'keep'


# ---- cancellation ------------------------------------------------------------------

def test_cancel_at_every_checkpoint_publishes_nothing(tmp_path):
    source = make(tmp_path / 'in.tif', np.ones((1, 130, 300), np.uint8))
    calls = {'n': 0}

    def count():
        calls['n'] += 1
        return False
    engine.run_job(dict(source=source, output=str(tmp_path / 'count.tif'), bands=[1]), FakePredictor(),
                   canceled=count)
    for stop_at in range(1, calls['n'] + 1):
        seen = {'n': 0}

        def canceled(seen=seen, stop_at=stop_at):
            seen['n'] += 1
            return seen['n'] >= stop_at
        with pytest.raises(Cancelled):
            engine.run_job(dict(source=source, output=str(tmp_path / 'out.tif'), bands=[1]),
                           FakePredictor(), canceled=canceled)
        assert_nothing_published(tmp_path)


def test_a_cancel_after_the_output_is_complete_still_stops_publication(tmp_path, monkeypatch):
    state = {'cancel': False}
    real = raster.OutputRaster.finish

    def finish_then_cancel(self):
        real(self)
        state['cancel'] = True
    monkeypatch.setattr(raster.OutputRaster, 'finish', finish_then_cancel)
    with pytest.raises(Cancelled):
        engine.run_job(dict(source=small(tmp_path), output=str(tmp_path / 'out.tif'), bands=[1]),
                       FakePredictor(), canceled=lambda: state['cancel'])
    assert_nothing_published(tmp_path)


def test_progress_rises_to_one_hundred(tmp_path):
    seen = []
    engine.run_job(dict(source=small(tmp_path, size=200), output=str(tmp_path / 'out.tif'), bands=[1]),
                   FakePredictor(), progress=seen.append)
    assert seen == sorted(seen) and seen[-1] == 100.0
