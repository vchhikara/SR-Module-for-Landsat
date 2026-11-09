"""Experimental QGIS interface for RGB super-resolution."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import traceback

from osgeo import gdal
import numpy as np
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (QAction, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QDoubleSpinBox, QVBoxLayout, QWidget)
from qgis.core import QgsApplication, QgsProject, QgsRasterLayer, QgsTask, QgsMessageLog, Qgis

PLUGIN_DIR = Path(__file__).resolve().parent
LANDSAT = __package__.split('.')[0] == 'landsat_sr'
TITLE = 'SR Module for Landsat' if LANDSAT else 'RGB SR Module Mono'

class RunTask(QgsTask):
    """Process bounded raster windows and write incrementally to a GeoTIFF."""
    def __init__(self, options, on_done):
        super().__init__(TITLE, QgsTask.Flag.CanCancel)
        self.options, self.on_done = options, on_done
        self.error = ''
        self.debug_traceback = ''
        self.process = None

    def run(self):
        o = self.options
        source = out = None
        temporary = None
        try:
            source = gdal.Open(o['source'], gdal.GA_ReadOnly)
            if source is None:
                raise ValueError('GDAL could not open the selected raster.')
            width, height = source.RasterXSize, source.RasterYSize
            if width <= 0 or height <= 0:
                raise ValueError('Input raster is empty.')
            mode = o.get('input_mode','auto')
            if mode not in ('auto','mono','rgb'):
                raise ValueError('Unknown input mode.')
            gray_alpha = (source.RasterCount == 2 and
                          source.GetRasterBand(2).GetColorInterpretation() == gdal.GCI_AlphaBand)
            mono = mode == 'mono' or (mode == 'auto' and (source.RasterCount == 1 or gray_alpha))
            indexes = o['bands'][:1] if mono else o['bands']
            o['input_mode_resolved'] = 'mono' if mono else 'rgb'
            o['processed_bands'] = indexes
            selected = []
            for index in indexes:
                band = source.GetRasterBand(index)
                if band is None:
                    raise ValueError('Selected band %s does not exist.' % index)
                selected.append(band)
            types = {band.DataType for band in selected}
            if len(types) != 1 or not types.issubset({gdal.GDT_Byte,gdal.GDT_UInt16}):
                raise ValueError('Select 8-bit or unsigned 16-bit bands of the same data type.')
            datatype = selected[0].DataType
            dtype = np.uint8 if datatype == gdal.GDT_Byte else np.uint16
            if not LANDSAT or o.get('auto_range', True):
                o['minimum'] = 0.0
                o['maximum'] = 255.0 if datatype == gdal.GDT_Byte else 65535.0
            o['output_bit_depth'] = 8 if datatype == gdal.GDT_Byte else 16
            if o['maximum'] <= o['minimum']:
                raise ValueError('Display range maximum must exceed its minimum.')
            has_mask = any((b.GetMaskFlags() & gdal.GMF_ALL_VALID) == 0 for b in selected)
            dest = Path(o['output'])
            if not dest.parent.is_dir(): raise ValueError('Output folder does not exist.')
            if dest.exists() or Path(str(dest)+'.json').exists():
                raise FileExistsError('Output or report already exists; choose a new filename.')
            blocks = ((width + 191)//192) * ((height + 191)//192)
            used = set()
            invalid_pixels = 0
            with tempfile.TemporaryDirectory(prefix='.qgis_sr_', dir=str(dest.parent), ignore_cleanup_errors=True) as temporary:
                temp = Path(temporary)
                infile, outfile = temp/'input.npy', temp/'output.npy'
                response, log_file = temp/'response.json', temp/'worker.log'
                staging = temp/'result.tif'
                env = os.environ.copy()
                for key in ('PYTHONHOME','PYTHONPATH','QT_PLUGIN_PATH'):
                    env.pop(key, None)
                cmd = [o['python'], str(PLUGIN_DIR/'stream_worker.py'),
                       str(Path(o['weights'])/'real_hat_64.onnx'), o['device']]
                with log_file.open('w', encoding='utf-8') as log:
                    self.process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,  # nosec B603
                         text=True, encoding='utf-8', env=env,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    driver = gdal.GetDriverByName('GTiff')
                    data_bands = 1 if mono else 3
                    out = driver.Create(str(staging), width*4, height*4, data_bands + (1 if has_mask else 0),
                           datatype, options=['COMPRESS=DEFLATE','TILED=YES','BIGTIFF=IF_SAFER',
                                             'PHOTOMETRIC=MINISBLACK' if mono else 'PHOTOMETRIC=RGB'])
                    if out is None: raise RuntimeError('Could not create output GeoTIFF.')
                    transform = source.GetGeoTransform(can_return_null=True)
                    if transform is not None:
                        out.SetGeoTransform((transform[0], transform[1]/4, transform[2]/4,
                                             transform[3], transform[4]/4, transform[5]/4))
                    if source.GetProjection(): out.SetProjection(source.GetProjection())
                    colours = (gdal.GCI_GrayIndex,) if mono else (gdal.GCI_RedBand,gdal.GCI_GreenBand,gdal.GCI_BlueBand)
                    for i, colour in enumerate(colours, 1):
                        out.GetRasterBand(i).SetColorInterpretation(colour)
                    if has_mask: out.GetRasterBand(data_bands+1).SetColorInterpretation(gdal.GCI_AlphaBand)
                    out.SetMetadataItem('SR_NOTICE','Estimated visual detail; not verified ground truth.')
                    done = 0
                    for y in range(0, height, 192):
                        for x in range(0, width, 192):
                            if self.isCanceled(): raise RuntimeError('Cancelled.')
                            cw, ch = min(192,width-x), min(192,height-y)
                            x0, y0 = max(0,x-32), max(0,y-32)
                            x1, y1 = min(width,x+cw+32), min(height,y+ch+32)
                            ww, wh = x1-x0, y1-y0
                            valid = np.ones((wh,ww), dtype=bool)
                            arrays = []
                            for band in selected:
                                data = band.ReadAsArray(x0,y0,ww,wh)
                                if data is None: raise RuntimeError('Could not read input raster window.')
                                data = data.astype(np.float32)
                                valid &= np.isfinite(data)
                                if (band.GetMaskFlags() & gdal.GMF_ALL_VALID) == 0:
                                    valid &= band.GetMaskBand().ReadAsArray(x0,y0,ww,wh) != 0
                                arrays.append(data)
                            image = np.stack(arrays,axis=-1)
                            if valid.any() and (image[valid].min()<o['minimum'] or image[valid].max()>o['maximum']):
                                raise ValueError('Valid input pixels are outside the selected display range.')
                            image[~valid] = o['minimum']
                            image = (image-o['minimum'])/(o['maximum']-o['minimum'])
                            if mono:
                                image = np.repeat(image,3,axis=2)
                            np.save(infile,image,allow_pickle=False)
                            response.unlink(missing_ok=True); outfile.unlink(missing_ok=True)
                            job = {'input':str(infile),'output':str(outfile),'response':str(response)}
                            self.process.stdin.write(json.dumps(job)+'\n'); self.process.stdin.flush()
                            while not response.is_file():
                                if self.isCanceled(): raise RuntimeError('Cancelled.')
                                if self.process.poll() is not None:
                                    raise RuntimeError('Model worker stopped. '+log_file.read_text(encoding='utf-8',errors='replace')[-4000:])
                                time.sleep(.15)
                            reply = json.loads(response.read_text(encoding='utf-8'))
                            if not reply.get('ok'): raise RuntimeError('Model error:\n'+reply.get('error','unknown error'))
                            used.add(reply['backend'])
                            result = np.load(outfile,allow_pickle=False)
                            if result.shape != (wh*4,ww*4,3): raise ValueError('Unexpected model output dimensions.')
                            ox, oy = (x-x0)*4, (y-y0)*4
                            numeric_max = 255 if datatype == gdal.GDT_Byte else 65535
                            cropped = result[oy:oy+ch*4,ox:ox+cw*4]
                            if mono:
                                cropped = (cropped[...,0]*0.2126 + cropped[...,1]*0.7152 + cropped[...,2]*0.0722)[...,None]
                            cropped = np.clip(cropped*numeric_max,0,numeric_max).round().astype(dtype)
                            for i in range(data_bands):
                                if out.GetRasterBand(i+1).WriteArray(cropped[...,i],x*4,y*4) != 0:
                                    raise RuntimeError('Could not write output raster window.')
                            if has_mask:
                                v = valid[y-y0:y-y0+ch,x-x0:x-x0+cw]
                                invalid_pixels += int((~v).sum())
                                alpha = np.repeat(np.repeat(v.astype(dtype)*numeric_max,4,axis=0),4,axis=1)
                                if out.GetRasterBand(data_bands+1).WriteArray(alpha,x*4,y*4) != 0:
                                    raise RuntimeError('Could not write output alpha mask.')
                            done += 1
                            self.setProgress(100.0*done/blocks)
                    self.process.stdin.write('{"stop":true}\n'); self.process.stdin.flush()
                    self.process.wait(timeout=30)
                    if self.process.returncode: raise RuntimeError('Model worker failed during shutdown.')
                    self.process = None
                    out.FlushCache(); out = None
                if self.isCanceled(): raise RuntimeError('Cancelled.')
                o['backend'] = ', '.join(sorted(used))
                report = {**o,'module':TITLE,'scale':4,'blocks':blocks,'invalid_input_pixels':invalid_pixels,
                          'output_type':str(o['output_bit_depth'])+('‑bit monochrome' if mono else '‑bit RGB')+' visualization','notice':'Estimated detail; not validated ground truth.',
                          'mask_note':'Invalid pixels are transparent; nearby model predictions may be affected.' if has_mask else None}
                report_temp = temp/'report.json'
                report_temp.write_text(json.dumps(report,indent=2),encoding='utf-8')
                if dest.exists() or Path(str(dest)+'.json').exists():
                    raise FileExistsError('Output or report appeared while processing; no files were replaced.')
                os.rename(staging,dest)
                os.rename(report_temp,Path(str(dest)+'.json'))
            return True
        except Exception as exc:
            self.error = str(exc)
            self.debug_traceback = traceback.format_exc()
            return False
        finally:
            out = None
            source = None
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                try: self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill(); self.process.wait()
            self.process = None
            if temporary and Path(temporary).name.startswith('.qgis_sr_'):
                import shutil
                shutil.rmtree(temporary, ignore_errors=True)

    def finished(self, success):
        if not success and self.debug_traceback:
            QgsMessageLog.logMessage(self.debug_traceback, TITLE, Qgis.MessageLevel.Critical)
        self.on_done(success,self.error,self.options)


class SuperResolutionPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.task = None

    def initGui(self):
        self.action = QAction(QIcon(str(PLUGIN_DIR / 'icon.png')), TITLE, self.iface.mainWindow())
        self.action.triggered.connect(self.show_dialog)
        self.iface.addPluginToRasterMenu(TITLE, self.action)
        self.iface.addToolBarIcon(self.action)
    def unload(self):
        self.iface.removePluginRasterMenu(TITLE, self.action)
        self.iface.removeToolBarIcon(self.action)

    def show_dialog(self):
        d = QDialog(self.iface.mainWindow())
        d.setWindowTitle(TITLE)
        layout = QVBoxLayout(d)
        notice = QLabel('Experimental visual enhancement. Generated detail is estimated, not verified ground truth.' +
                        (' Landsat mode outputs only an 8-bit RGB display image; it is not multispectral SR.' if LANDSAT else ''))
        notice.setWordWrap(True)
        layout.addWidget(notice)
        form = QFormLayout()
        layout.addLayout(form)
        layers = QComboBox()
        layers.addItem('Select loaded raster or choose file below', '')
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsRasterLayer) and layer.isValid():
                layers.addItem(layer.name(), layer.source())
        form.addRow('QGIS raster layer', layers)
        def file_row(label, directory=False, save=False):
            edit, button, box = QLineEdit(), QPushButton('Browse…'), QWidget()
            row = QHBoxLayout(box); row.setContentsMargins(0, 0, 0, 0); row.addWidget(edit); row.addWidget(button)
            def browse():
                path = (QFileDialog.getExistingDirectory(d, label) if directory else
                        (QFileDialog.getSaveFileName(d, label, '', 'GeoTIFF (*.tif *.tiff)')[0] if save else
                         QFileDialog.getOpenFileName(d, label)[0]))
                if path: edit.setText(path)
            button.clicked.connect(browse); form.addRow(label, box)
            return edit
        file_input = file_row('Input file (overrides layer)')
        mode = QComboBox(); mode.addItem('Automatic', 'auto'); mode.addItem('Monochrome', 'mono'); mode.addItem('RGB', 'rgb'); form.addRow('Input type', mode)
        spins = []
        for label, default in [('Red / mono band', 1), ('Green band', 2), ('Blue band', 3)]:
            spin = QSpinBox(); spin.setRange(1, 999); spin.setValue(default); form.addRow(label, spin); spins.append(spin)
        def update_bands():
            for spin in spins[1:]: spin.setEnabled(mode.currentData() != 'mono')
        mode.currentIndexChanged.connect(update_bands)
        update_bands()
        minimum, maximum = QDoubleSpinBox(), QDoubleSpinBox()
        for s in (minimum, maximum): s.setRange(-100000000, 100000000); s.setDecimals(3)
        maximum.setValue(65535 if LANDSAT else 255)
        auto_range = QCheckBox('Use full input bit-depth range'); auto_range.setChecked(True)
        if LANDSAT:
            form.addRow('Display scaling', auto_range)
            form.addRow('Display input minimum', minimum); form.addRow('Display input maximum', maximum)
            minimum.setEnabled(False); maximum.setEnabled(False)
            def change_range(checked):
                minimum.setEnabled(not checked); maximum.setEnabled(not checked)
            auto_range.toggled.connect(change_range)
        model = QComboBox(); model.addItem('real-hat-sharper'); form.addRow('Model', model)
        device = QComboBox(); device.addItems(['auto', 'gpu', 'cpu']); form.addRow('Device', device)

        output = file_row('Output GeoTIFF', save=True)
        add = QCheckBox('Add output to QGIS'); add.setChecked(True); layout.addWidget(add)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(d.accept); buttons.rejected.connect(d.reject); layout.addWidget(buttons)
        if d.exec() != QDialog.DialogCode.Accepted: return
        src = file_input.text().strip() or layers.currentData()
        dst = output.text().strip()
        if not src or not dst:
            QMessageBox.warning(self.iface.mainWindow(), TITLE, 'Choose an input and an output.'); return
        if not auto_range.isChecked() and maximum.value() <= minimum.value():
            QMessageBox.warning(self.iface.mainWindow(), TITLE, 'Maximum must exceed minimum.'); return
        if Path(dst).exists() or Path(dst + '.json').exists():
            QMessageBox.warning(self.iface.mainWindow(), TITLE, 'Output or its report already exists. Choose a new name.'); return
        if not dst.lower().endswith(('.tif', '.tiff')):
            QMessageBox.warning(self.iface.mainWindow(), TITLE, 'Output must end in .tif or .tiff.'); return
        runtime = PLUGIN_DIR / 'runtime' / 'python.exe'
        model_file = PLUGIN_DIR / 'weights' / 'real_hat_64.onnx'
        if not runtime.is_file() or not model_file.is_file():
            QMessageBox.warning(self.iface.mainWindow(), TITLE,
                'The offline runtime or model file is missing from the plugin folder. '
                'Install the complete plugin package from the project maintainer.'); return
        options = dict(source=src, output=dst, bands=[s.value() for s in spins], input_mode=mode.currentData(), auto_range=auto_range.isChecked(), minimum=minimum.value(), maximum=maximum.value(),
                       python=str(PLUGIN_DIR / 'runtime' / 'python.exe'), weights=str(PLUGIN_DIR / 'weights'), model=model.currentText(), device=device.currentText(), tile=64, add=add.isChecked())
        self.task = RunTask(options, self.finished)
        QgsApplication.taskManager().addTask(self.task)
        self.iface.messageBar().pushInfo(TITLE, 'Processing started. See QGIS Tasks for progress and cancellation.')

    def finished(self, success, error, options):
        if not success:
            QMessageBox.warning(self.iface.mainWindow(), TITLE, error or 'Processing failed or was cancelled.')
        else:
            if options['add']:
                self.iface.addRasterLayer(options['output'], Path(options['output']).stem)
            self.iface.messageBar().pushSuccess(TITLE, 'Output and processing report saved. Backend: ' + options.get('backend', 'unknown'))

