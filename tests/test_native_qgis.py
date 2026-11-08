"""Native tests. They need real QGIS bindings (python3-qgis) and skip without them."""
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

qgis_core = pytest.importorskip('qgis.core')
from qgis.PyQt.QtWidgets import QApplication, QDialog, QMainWindow  # noqa: E402
from qgis.core import Qgis, QgsApplication, QgsTask  # noqa: E402


@pytest.fixture(scope='module')
def qgs():
    app = QgsApplication([], False)
    app.initQgis()
    yield app
    app.exitQgis()


@pytest.fixture()
def plugin(qgs):
    import landsat_sr
    window = QMainWindow()
    iface = mock.MagicMock()
    iface.mainWindow.return_value = window
    instance = landsat_sr.classFactory(iface)
    yield instance, iface
    window.close()


def test_scoped_enums_exist():
    assert QgsTask.Flag.CanCancel is not None
    assert Qgis.MessageLevel.Critical is not None
    assert QDialog.DialogCode.Accepted is not None


def test_init_gui_and_unload(plugin):
    instance, iface = plugin
    instance.initGui()
    iface.addPluginToRasterMenu.assert_called_once()
    iface.addToolBarIcon.assert_called_once()
    instance.unload()
    iface.removePluginRasterMenu.assert_called_once()
    iface.removeToolBarIcon.assert_called_once()


def test_dialog_cancel_starts_no_task(plugin):
    instance, iface = plugin
    instance.initGui()
    with mock.patch.object(QDialog, 'exec', return_value=QDialog.DialogCode.Rejected):
        instance.show_dialog()
    assert instance.task is None
    instance.unload()


def test_missing_runtime_is_reported(plugin, tmp_path):
    instance, iface = plugin
    instance.initGui()
    source = tmp_path / 'in.tif'
    source.write_bytes(b'x')
    target = tmp_path / 'out.tif'
    from qgis.PyQt.QtWidgets import QLineEdit
    original = QLineEdit.text
    texts = iter([str(source), str(target)])

    def fake_text(self):
        try:
            return next(texts)
        except StopIteration:
            return original(self)

    with mock.patch.object(QDialog, 'exec', return_value=QDialog.DialogCode.Accepted), \
         mock.patch.object(QLineEdit, 'text', fake_text), \
         mock.patch('landsat_sr.plugin.QMessageBox.warning') as warning:
        instance.show_dialog()
    assert warning.called
    assert 'missing' in warning.call_args[0][2].lower()
    assert instance.task is None
    instance.unload()
