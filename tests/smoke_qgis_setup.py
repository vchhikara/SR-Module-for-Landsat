"""Manual: runtime configuration in an isolated QGIS settings profile. This runs the supplied runtime."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import MagicMock, patch

from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTimer
from qgis.PyQt.QtWidgets import QApplication, QDialog, QLineEdit, QMainWindow, QMessageBox
from qgis.core import QgsApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
bundle = Path(os.environ['LANDSAT_SR_RUNTIME_PACKAGE'])
with tempfile.TemporaryDirectory() as directory:
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, directory)
    QCoreApplication.setOrganizationName('LandsatSRTest')
    QCoreApplication.setApplicationName('LandsatSRTest')
    app = QgsApplication([], True, directory)
    app.initQgis()
    from landsat_sr.plugin import SuperResolutionPlugin
    window = QMainWindow()
    iface = MagicMock()
    iface.mainWindow.return_value = window
    plugin = SuperResolutionPlugin(iface)
    plugin.initGui()
    def fill_dialog():
        dialog = next(w for w in QApplication.topLevelWidgets()
                      if isinstance(w, QDialog) and w.windowTitle() == 'Configure SR runtime and model')
        fields = dialog.findChildren(QLineEdit)
        assert len(fields) == 2
        fields[0].setText(str(bundle / 'runtime' / 'python.exe'))
        fields[1].setText(str(bundle / 'weights' / 'real_hat_64.onnx'))
        dialog.accept()
    QTimer.singleShot(100, fill_dialog)
    with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
        assert plugin.configure_runtime()
    python, model = plugin.runtime_paths()
    assert python == bundle / 'runtime' / 'python.exe'
    assert model == bundle / 'weights' / 'real_hat_64.onnx'
    assert len(plugin.trusted_fingerprint(python)) == 64
    plugin.unload()
    assert iface.addPluginToRasterMenu.call_count == 2
    assert iface.removePluginRasterMenu.call_count == 2
    print('Runtime setup, persistence and menu unload passed', flush=True)
    window.close()
    app.exitQgis()
