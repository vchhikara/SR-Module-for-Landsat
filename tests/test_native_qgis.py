"""Native QGIS tests with the real task manager and event loop. They skip without python3-qgis."""
import time
from unittest import mock

import pytest

qgis_core = pytest.importorskip('qgis.core')
from qgis.PyQt.QtWidgets import QDialog, QMainWindow, QMessageBox  # noqa: E402
from qgis.core import QgsApplication, QgsRasterLayer  # noqa: E402

from conftest import FakePredictor, nearest4  # noqa: E402


@pytest.fixture(scope='module')
def qgs(tmp_path_factory):
    from qgis.PyQt.QtCore import QCoreApplication, QSettings
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                      str(tmp_path_factory.mktemp('settings')))
    QCoreApplication.setOrganizationName('LandsatSRTest')
    QCoreApplication.setApplicationName('LandsatSRTest')
    app = QgsApplication([], False)
    app.initQgis()
    yield app
    app.exitQgis()
    from osgeo import gdal
    gdal.AllRegister()  # exitQgis removes the GDAL drivers that later tests need


@pytest.fixture()
def plugin(qgs):
    import landsat_sr
    from qgis.PyQt.QtCore import QSettings
    QSettings().clear()
    window = QMainWindow()
    iface = mock.MagicMock()
    iface.mainWindow.return_value = window
    instance = landsat_sr.classFactory(iface)
    instance.initGui()
    unexpected = AssertionError('an unexpected modal dialog would block the test')
    with mock.patch.object(QMessageBox, 'warning', side_effect=unexpected), \
            mock.patch.object(QMessageBox, 'information', side_effect=unexpected), \
            mock.patch.object(QMessageBox, 'question', side_effect=unexpected):
        yield instance, iface
    if instance.tasks:
        instance.unload()
    window.close()


def raster_file(path, size=300):
    from osgeo import gdal
    ds = gdal.GetDriverByName('GTiff').Create(str(path), size, size, 1, gdal.GDT_Byte)
    ds.GetRasterBand(1).Fill(77)
    ds.SetGeoTransform((0, 30, 0, 0, 0, -30))
    ds = None
    return str(path)


def options(tmp_path, name='out.tif', **extra):
    base = dict(source=raster_file(tmp_path / ('in_' + name)), output=str(tmp_path / name), bands=[1, 2, 3],
                input_mode='auto', auto_range=True, minimum=0, maximum=255, device='cpu', add=True,
                python='unused', model_path='unused', runtime_fingerprint='unused')
    base.update(extra)
    return base


def slow_predictor(delay, state):
    def change(batch):
        state['started'] = True
        time.sleep(delay)
        return nearest4(batch)

    def factory(task, log_path):
        return FakePredictor(change)
    return factory


def pump(qgs, condition, timeout=30):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, 'timed out'
        qgs.processEvents()
        time.sleep(0.01)


def test_a_real_task_publishes_and_reports(qgs, plugin, tmp_path):
    from landsat_sr import plugin as module
    instance, iface = plugin
    with mock.patch.object(module.RunTask, '_predictor', slow_predictor(0, {})):
        instance.start_task(options(tmp_path))
        pump(qgs, lambda: not instance.tasks)
    assert (tmp_path / 'out.tif').is_file() and (tmp_path / 'out.tif.json').is_file()
    iface.addRasterLayer.assert_called_once()
    assert 'CPU' in iface.messageBar().pushSuccess.call_args[0][1]
    assert not module._LIVE_TASKS


def test_unload_during_inference_cancels_and_stays_silent(qgs, plugin, tmp_path):
    from landsat_sr import plugin as module
    instance, iface = plugin
    state = {}
    with mock.patch.object(module.RunTask, '_predictor', slow_predictor(0.3, state)), \
            mock.patch.object(QMessageBox, 'warning') as warning:
        task = instance.start_task(options(tmp_path))
        pump(qgs, lambda: state.get('started'))
        instance.unload()
        assert task.on_done is None and not instance.tasks
        pump(qgs, lambda: task not in module._LIVE_TASKS)
    warning.assert_not_called()
    iface.addRasterLayer.assert_not_called()
    iface.messageBar().pushSuccess.assert_not_called()
    assert not (tmp_path / 'out.tif').exists() and not list(tmp_path.glob('.qgis_sr_*'))


def test_two_tasks_are_tracked_and_the_same_output_is_refused(qgs, plugin, tmp_path):
    from landsat_sr import plugin as module
    instance, _ = plugin
    with mock.patch.object(module.RunTask, '_predictor', slow_predictor(0.2, {})):
        instance.start_task(options(tmp_path, 'a.tif'))
        instance.start_task(options(tmp_path, 'b.tif'))
        assert len(instance.tasks) == 2
        assert 'already writes' in instance._check_options(options(tmp_path / '.', 'a.tif'))
        pump(qgs, lambda: not instance.tasks)
    assert (tmp_path / 'a.tif').is_file() and (tmp_path / 'b.tif').is_file()


def test_a_failure_shows_a_redacted_message(qgs, plugin, tmp_path):
    from landsat_sr import plugin as module
    instance, _ = plugin

    def explode(task, log_path):
        raise KeyError('token=hunter2')
    logged = []
    log = QgsApplication.messageLog()
    # QGIS 4.2.0 on Windows emits only the newer signal. QGIS 3.34 may have only the older one.
    signal = getattr(log, 'messageReceivedWithFormat', None) or log.messageReceived
    signal.connect(lambda message, *args: logged.append(message))
    with mock.patch.object(module.RunTask, '_predictor', explode), \
            mock.patch.object(QMessageBox, 'warning') as warning:
        instance.start_task(options(tmp_path))
        pump(qgs, lambda: not instance.tasks)
        qgs.processEvents()
    assert 'hunter2' not in warning.call_args[0][2] and 'Processing failed' in warning.call_args[0][2]
    assert any('KeyError' in m for m in logged) and not any('hunter2' in m for m in logged)


def test_an_untrusted_runtime_blocks_the_real_task(qgs, plugin, tmp_path):
    instance, _ = plugin
    with mock.patch.object(QMessageBox, 'warning') as warning:
        instance.start_task(options(tmp_path, runtime_fingerprint=''))
        pump(qgs, lambda: not instance.tasks)
    assert 'not trusted' in warning.call_args[0][2]


def accept_with(values):
    """Fill the line edits of the next dialog in order, then accept it."""
    from qgis.PyQt.QtWidgets import QAbstractSpinBox, QLineEdit

    def fake_exec(dialog):
        # Spin boxes own a hidden QLineEdit, so leave those out.
        edits = [e for e in dialog.findChildren(QLineEdit) if not isinstance(e.parent(), QAbstractSpinBox)]
        for edit, value in zip(edits, values):
            edit.setText(value)
        return QDialog.DialogCode.Accepted
    return mock.patch.object(QDialog, 'exec', fake_exec)


def fake_runtime(tmp_path):
    root = tmp_path / 'runtime'
    root.mkdir()
    marker = tmp_path / 'executed'
    python = root / 'python.exe'
    python.write_text('#!/bin/sh\ntouch "{}"\n'.format(marker))
    python.chmod(0o755)
    return python, marker


def test_nothing_runs_when_the_user_declines_trust(qgs, plugin, tmp_path):
    instance, _ = plugin
    python, marker = fake_runtime(tmp_path)
    with accept_with([str(python), 'model']), \
            mock.patch('landsat_sr.runtime_config.check_paths', return_value=''), \
            mock.patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
        assert instance.configure_runtime() is False
    assert not marker.exists() and instance.trusted_fingerprint(python) == ''


def test_trust_is_stored_after_a_good_probe_only(qgs, plugin, tmp_path):
    from landsat_sr.constants import SRError
    instance, _ = plugin
    python, _ = fake_runtime(tmp_path)
    yes = QMessageBox.StandardButton.Yes
    common = [mock.patch('landsat_sr.runtime_config.check_paths', return_value=''),
              mock.patch.object(QMessageBox, 'question', return_value=yes)]
    with accept_with([str(python), 'model']), common[0], common[1], \
            mock.patch('landsat_sr.runtime_config.probe', side_effect=SRError('too old')), \
            mock.patch.object(QMessageBox, 'warning'):
        assert instance.configure_runtime() is False
    assert instance.trusted_fingerprint(python) == ''
    with accept_with([str(python), 'model']), \
            mock.patch('landsat_sr.runtime_config.check_paths', return_value=''), \
            mock.patch.object(QMessageBox, 'question', return_value=yes), \
            mock.patch('landsat_sr.runtime_config.probe', return_value={}):
        assert instance.configure_runtime() is True
    assert len(instance.trusted_fingerprint(python)) == 64


def test_the_dialog_offers_only_local_gdal_layers(qgs, plugin, tmp_path):
    from landsat_sr.plugin import local_layer_path
    path = raster_file(tmp_path / 'layer.tif', 8)
    assert local_layer_path(QgsRasterLayer(path, 'file', 'gdal')) == path
    remote = QgsRasterLayer('url=http://127.0.0.1:1/wms&layers=a&crs=EPSG:4326&styles=&format=image/png&'
                            'password=hunter2', 'remote', 'wms')
    assert local_layer_path(remote) == ''


def test_dialog_cancel_starts_no_task(plugin):
    instance, _ = plugin
    with mock.patch.object(QDialog, 'exec', return_value=QDialog.DialogCode.Rejected):
        instance.show_dialog()
    assert not instance.tasks


def test_missing_runtime_is_reported(plugin, tmp_path):
    instance, _ = plugin
    source = raster_file(tmp_path / 'in.tif', 8)
    with accept_with([source, str(tmp_path / 'out.tif')]), \
            mock.patch('landsat_sr.plugin.QMessageBox.information') as info, \
            mock.patch.object(instance, 'configure_runtime', return_value=False):
        instance.show_dialog()
    assert 'setup' in info.call_args[0][2].lower() and not instance.tasks


def test_init_gui_and_unload(plugin):
    instance, iface = plugin
    assert iface.addPluginToRasterMenu.call_count == 2
    instance.unload()
    assert iface.removePluginRasterMenu.call_count == 2
    iface.removeToolBarIcon.assert_called_once()


