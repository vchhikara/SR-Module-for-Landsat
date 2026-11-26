# SPDX-License-Identifier: GPL-3.0-or-later
"""QGIS interface: dialogs, the background task and its lifecycle."""
import os
from pathlib import Path
import traceback

from qgis.PyQt.QtCore import QSettings, Qt
from qgis.PyQt.QtGui import QCursor, QIcon
from qgis.PyQt.QtWidgets import (QAction, QApplication, QCheckBox, QComboBox, QDialog,
                                 QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                                 QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox,
                                 QVBoxLayout, QWidget)
from qgis.core import Qgis, QgsApplication, QgsMessageLog, QgsProject, QgsRasterLayer, QgsTask

from . import engine, publish, runtime_config
from .constants import MODEL_NAME, MODEL_SHA256, Cancelled, SRError
from .redact import redact
from .worker_client import Worker

PLUGIN_DIR = Path(__file__).resolve().parent
TITLE = 'SR Module for Landsat'
RUNTIME_KEY = '/LandsatSR/runtime_python'
MODEL_KEY = '/LandsatSR/model_file'
TRUST_PYTHON_KEY = '/LandsatSR/trusted_python'
TRUST_KEY = '/LandsatSR/trusted_fingerprint'

# QGIS can still run a task after the plugin is unloaded. This keeps its Python object alive.
_LIVE_TASKS: set = set()


class RunTask(QgsTask):
    """Run one job in the background. run() must not touch any widget."""

    def __init__(self, options, on_done):
        super().__init__(TITLE, QgsTask.Flag.CanCancel)
        self.options, self.on_done = options, on_done
        self.error = ''
        self.debug_traceback = ''
        self.report = None

    def _predictor(self, log_path):
        o = self.options
        runtime_config.verify_trusted(o['python'], o['runtime_fingerprint'])
        return Worker(o['python'], o['model_path'], o['device'], MODEL_SHA256, log_path, self.isCanceled)

    def run(self):
        try:
            self.report = engine.run_job(self.options, self._predictor, self.setProgress, self.isCanceled)
            return True
        except Cancelled as exc:
            self.error = str(exc)
        except SRError as exc:
            self.error = redact(exc)
        except Exception as exc:  # a task must always report, never crash QGIS
            self.error = 'Processing failed: ' + redact(exc)
            self.debug_traceback = redact(traceback.format_exc())
        return False

    def finished(self, success):
        """Called by QGIS on the main thread."""
        _LIVE_TASKS.discard(self)
        if not success and self.debug_traceback:
            QgsMessageLog.logMessage(self.debug_traceback, TITLE, Qgis.MessageLevel.Critical)
        if self.on_done is not None:
            self.on_done(self, bool(success))


def _destination_key(path):
    return os.path.normcase(os.path.abspath(path))


def local_layer_path(layer):
    """The file path of a layer that GDAL reads from one local file, else ''."""
    if layer.providerType() != 'gdal':
        return ''
    source = layer.source()
    return source if '://' not in source and os.path.isfile(source) else ''


class SuperResolutionPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.tasks: dict = {}  # destination -> RunTask

    def initGui(self):
        self.action = QAction(QIcon(str(PLUGIN_DIR / 'icon.png')), TITLE, self.iface.mainWindow())
        self.action.triggered.connect(self.show_dialog)
        self.iface.addPluginToRasterMenu(TITLE, self.action)
        self.iface.addToolBarIcon(self.action)
        self.setup_action = QAction('Configure SR runtime and model…', self.iface.mainWindow())
        self.setup_action.triggered.connect(self.configure_runtime)
        self.iface.addPluginToRasterMenu(TITLE, self.setup_action)

    def unload(self):
        """Detach first, so no callback reaches the GUI, then cancel and wait briefly."""
        tasks, self.tasks = list(self.tasks.values()), {}
        for task in tasks:
            task.on_done = None
        for task in tasks:
            try:
                task.cancel()
                task.waitForFinished(5000)
            except RuntimeError:
                pass  # QGIS already deleted the task
        self.iface.removePluginRasterMenu(TITLE, self.action)
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginRasterMenu(TITLE, self.setup_action)
        self.action.deleteLater()
        self.setup_action.deleteLater()

    def _warn(self, message):
        QMessageBox.warning(self.iface.mainWindow(), TITLE, message)

    def runtime_paths(self):
        settings = QSettings()
        return runtime_config.resolve_paths(PLUGIN_DIR, settings.value(RUNTIME_KEY, '', type=str),
                                            settings.value(MODEL_KEY, '', type=str))

    def trusted_fingerprint(self, python):
        settings = QSettings()
        return runtime_config.trusted_fingerprint(
            PLUGIN_DIR, python, settings.value(TRUST_PYTHON_KEY, '', type=str),
            settings.value(TRUST_KEY, '', type=str))

    def confirm_trust(self, python):
        answer = QMessageBox.question(
            self.iface.mainWindow(), TITLE,
            'The plugin will run this program with your user rights:\n\n{}\n\nA runtime can do anything '
            'that you can do. The plugin cannot check who made it. Continue only if you got it from a '
            'source that you trust.'.format(python),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def configure_runtime(self):
        dialog = QDialog(self.iface.mainWindow())
        dialog.setWindowTitle('Configure SR runtime and model')
        layout = QVBoxLayout(dialog)
        label = QLabel('The QGIS repository package does not include the inference runtime or model. '
                       'Select them from a trusted complete SR runtime package. The model is checked '
                       'against its expected SHA-256. The runtime files are recorded, and a later change '
                       'blocks processing.')
        label.setWordWrap(True)
        layout.addWidget(label)
        form = QFormLayout()
        layout.addLayout(form)
        python_path, model_path = self.runtime_paths()
        python_edit, model_edit = QLineEdit(str(python_path)), QLineEdit(str(model_path))
        form.addRow('Runtime Python', self._file_row(dialog, python_edit, 'Select runtime Python',
                                                     'Python executable (python.exe);;All files (*)'))
        form.addRow('Model', self._file_row(dialog, model_edit, 'Select model file',
                                            'ONNX model (*.onnx);;All files (*)'))
        self._buttons(dialog, layout)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        python_path, model_path = python_edit.text().strip(), model_edit.text().strip()
        error = runtime_config.check_paths(python_path, model_path)
        if error:
            self._warn(error)
            return False
        if not self.confirm_trust(python_path):  # nothing from the runtime ran before this point
            return False
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            recorded = runtime_config.fingerprint(Path(python_path).parent)
            runtime_config.probe(python_path)
            runtime_config.verify_trusted(python_path, recorded)
        except SRError as exc:
            error = str(exc)
        finally:
            QApplication.restoreOverrideCursor()
        if error:
            self._warn(redact(error))
            return False
        settings = QSettings()
        settings.setValue(RUNTIME_KEY, python_path)
        settings.setValue(MODEL_KEY, model_path)
        settings.setValue(TRUST_PYTHON_KEY, str(Path(python_path)))
        settings.setValue(TRUST_KEY, recorded)
        return True

    @staticmethod
    def _file_row(dialog, edit, title, file_filter='', save=False):
        box = QWidget()
        line = QHBoxLayout(box)
        line.setContentsMargins(0, 0, 0, 0)
        button = QPushButton('Browse…')
        line.addWidget(edit)
        line.addWidget(button)

        def browse():
            chooser = QFileDialog.getSaveFileName if save else QFileDialog.getOpenFileName
            filename, _ = chooser(dialog, title, edit.text(), file_filter)
            if filename:
                edit.setText(filename)
        button.clicked.connect(browse)
        return box

    @staticmethod
    def _buttons(dialog, layout):
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

    def ask_options(self):
        """Show the processing dialog. Return the options, or None."""
        d = QDialog(self.iface.mainWindow())
        d.setWindowTitle(TITLE)
        layout = QVBoxLayout(d)
        notice = QLabel('Experimental visual enhancement. Generated detail is estimated, not verified ground '
                        'truth. Output is for visual display; it is not multispectral SR.')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        form = QFormLayout()
        layout.addLayout(form)
        layers = QComboBox()
        layers.addItem('Select loaded raster or choose file below', '')
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsRasterLayer) and layer.isValid() and local_layer_path(layer):
                layers.addItem(layer.name(), local_layer_path(layer))
        form.addRow('Local raster layer', layers)
        file_input, output = QLineEdit(), QLineEdit()
        form.addRow('Input file (overrides layer)', self._file_row(d, file_input, 'Input raster'))
        mode = QComboBox()
        for text, value in (('Automatic', 'auto'), ('Monochrome', 'mono'), ('RGB', 'rgb')):
            mode.addItem(text, value)
        form.addRow('Input type', mode)
        spins = []
        for text, default in (('Red / mono band', 1), ('Green band', 2), ('Blue band', 3)):
            spin = QSpinBox()
            spin.setRange(1, 999)
            spin.setValue(default)
            form.addRow(text, spin)
            spins.append(spin)

        def update_bands():
            for spin in spins[1:]:
                spin.setEnabled(mode.currentData() != 'mono')
        mode.currentIndexChanged.connect(update_bands)
        minimum, maximum = QDoubleSpinBox(), QDoubleSpinBox()
        for box in (minimum, maximum):
            box.setRange(-100000000, 100000000)
            box.setDecimals(3)
            box.setEnabled(False)
        maximum.setValue(65535)
        auto_range = QCheckBox('Use full input bit-depth range')
        auto_range.setChecked(True)
        auto_range.toggled.connect(lambda checked: [b.setEnabled(not checked) for b in (minimum, maximum)])
        form.addRow('Display scaling', auto_range)
        form.addRow('Display input minimum', minimum)
        form.addRow('Display input maximum', maximum)
        form.addRow('Model', QLabel(MODEL_NAME))
        device = QComboBox()
        device.addItems(['auto', 'gpu', 'cpu'])
        form.addRow('Device', device)
        form.addRow('Output GeoTIFF', self._file_row(d, output, 'Output GeoTIFF', 'GeoTIFF (*.tif *.tiff)', True))
        add = QCheckBox('Add output to QGIS')
        add.setChecked(True)
        layout.addWidget(add)
        self._buttons(d, layout)
        if d.exec() != QDialog.DialogCode.Accepted:
            return None
        return dict(source=file_input.text().strip() or layers.currentData(), output=output.text().strip(),
                    bands=[s.value() for s in spins], input_mode=mode.currentData(),
                    auto_range=auto_range.isChecked(), minimum=minimum.value(), maximum=maximum.value(),
                    device=device.currentText(), add=add.isChecked())

    def _check_options(self, options):
        if not options['source'] or not options['output']:
            return 'Choose an input and an output.'
        if not options['auto_range'] and options['maximum'] <= options['minimum']:
            return 'Maximum must exceed minimum.'
        if not options['output'].lower().endswith(('.tif', '.tiff')):
            return 'Output must end in .tif or .tiff.'
        if _destination_key(options['output']) in self.tasks:
            return 'A running task already writes this output. Choose a new name.'
        try:
            publish.check_free(options['output'])
        except SRError as exc:
            return str(exc)
        return ''

    def show_dialog(self):
        options = self.ask_options()
        if options is None:
            return
        error = self._check_options(options)
        if error:
            self._warn(error)
            return
        runtime, model_file = self.runtime_paths()
        error = runtime_config.check_paths(str(runtime), str(model_file))
        if not error and not self.trusted_fingerprint(runtime):
            error = 'The runtime is not trusted yet.'
        if error:
            QMessageBox.information(self.iface.mainWindow(), TITLE,
                                    'SR setup is needed before processing. ' + error +
                                    '\n\nChoose the runtime and model from the complete package in the next window.')
            if not self.configure_runtime():
                return
            runtime, model_file = self.runtime_paths()
        options.update(python=str(runtime), model_path=str(model_file),
                       runtime_fingerprint=self.trusted_fingerprint(runtime))
        self.start_task(options)

    def start_task(self, options):
        task = RunTask(options, self.finished)
        self.tasks[_destination_key(options['output'])] = task
        _LIVE_TASKS.add(task)
        QgsApplication.taskManager().addTask(task)
        self.iface.messageBar().pushInfo(TITLE, 'Processing started. See QGIS Tasks for progress and cancellation.')
        return task

    def finished(self, task, success):
        self.tasks.pop(_destination_key(task.options['output']), None)
        if not success:
            if task.isCanceled():
                # No dialog: QGIS also cancels tasks while it closes.
                self.iface.messageBar().pushInfo(TITLE, 'Processing was cancelled. No output was written.')
            else:
                self._warn(task.error or 'Processing failed.')
            return
        if task.report.get('private_files'):
            self.iface.messageBar().pushWarning(
                TITLE, 'Saved, but other users may not be able to read these files, because their folder '
                'permissions could not be applied: ' + ', '.join(task.report['private_files']))
        if task.options['add']:
            self.iface.addRasterLayer(task.options['output'], Path(task.options['output']).stem)
        self.iface.messageBar().pushSuccess(
            TITLE, 'Output and processing report saved. Backend: ' + task.report['backend'])
