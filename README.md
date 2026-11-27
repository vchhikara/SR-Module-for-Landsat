<h1 align="center">SR Module for Landsat</h1>

<p align="center">
  <img src="docs/images/banner.png" alt="SR Module for Landsat banner: a blocky Landsat scene on the left and a sharper enlarged scene on the right" width="100%">
</p>
<p align="center">
  <strong>Enlarge RGB and monochrome Landsat images four times for clearer display.</strong><br>
  Inference runs on your computer. It needs no internet connection and no cloud service.
</p>

<p align="center">
  <img alt="QGIS" src="https://img.shields.io/badge/QGIS-4.2-589632?logo=qgis&logoColor=white">
  <img alt="Python" src="https://img.shields.io/badge/Python-ONNX%20Runtime-3776AB?logo=python&logoColor=white">
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%2064--bit%20only-0078D4">
  <a href="landsat_sr/LICENSE"><img alt="License: GPL-3.0-or-later" src="https://img.shields.io/badge/license-GPL--3.0--or--later-blue"></a>
</p>

## Windows only: download the runtime and set it up

**This plugin works on Windows only.** It needs 64-bit Windows and QGIS 4.2 (tested with QGIS 4.2.0). Linux and macOS are not supported.

Setup is needed before first use. The plugin package has no runtime and no model, and the plugin does not download them.

1. Download [landsat_sr_runtime_windows_x64.zip](https://github.com/vchhikara/SR-Module-for-Landsat/releases/download/v0.7.0/landsat_sr_runtime_windows_x64.zip) (about 128 MB). The file is on the [v0.7.0 release page](https://github.com/vchhikara/SR-Module-for-Landsat/releases/tag/v0.7.0).
2. In the download folder, check the file in PowerShell:

   ```powershell
   Get-FileHash .\landsat_sr_runtime_windows_x64.zip
   ```

   The SHA-256 must be `54b502d8ef1d38f5995f534fe86647e0a3b8ca034e2a9d0046c9929917d0f9d8`. Capital and small letters are equal.
3. Extract the ZIP to a permanent folder that only you can change.
4. In QGIS, open **Raster → SR Module for Landsat → Configure SR runtime and model…**.
5. Select `runtime\python.exe` and `weights\real_hat_64.onnx`, then confirm that you trust the runtime.
6. Open **SR Module for Landsat** from the Raster menu. Select an input raster and a new `.tif` output path, then select **OK**.

Do not add or change files in the `runtime` folder. A change blocks processing until you configure the runtime again.

---

Landsat pixels are 30 meters wide, so small features look blocky on screen. SR Module for Landsat reads a prepared RGB or single-band raster, adds estimated detail with the Real-HAT model, and writes a GeoTIFF that is four times wider and four times taller. Use it for maps, presentations, and visual inspection.

What you can do:

- Enlarge an RGB raster or a single band by a factor of 4.
- Process 8-bit and unsigned 16-bit rasters.
- Pick a loaded QGIS layer or a file on disk.
- Process large rasters in blocks, with progress and cancel in QGIS Tasks.
- Run on a DirectML GPU, with automatic fallback to the CPU.

**The output serves visual display only.** The model estimates fine detail from an RGB-trained network. The result holds no verified ground information and no Landsat reflectance values.

---

## Features

| Feature | What it does |
|---|---|
| 4× enlargement | Writes a GeoTIFF with 4 times the width and height. It scales the geotransform, ground control points (GCPs) and RPCs, so the map position stays the same. |
| Input modes | Automatic, RGB, or Monochrome. Choose the band numbers for each color. |
| Display range | Uses the full bit-depth range by default. You can enter a minimum and a maximum. |
| Device choice | Automatic, GPU (DirectML), or CPU. |
| Masks and alpha | NoData and masked pixels become transparent. Partial alpha stays partial. |
| Report | Saves a JSON report next to the output. It lists the settings, backend and invalid pixel count. It records file names only, without folder paths or connection strings. |
| Safe output | The plugin does not replace existing files. It reads the finished GeoTIFF back and compares it before publication. A failed run leaves no GeoTIFF. |

---

## Requirements

- QGIS 4.2. It was tested on Windows with QGIS 4.2.0. The plugin metadata blocks other versions.
- 64-bit Windows only. Linux and macOS are not supported.
- A prepared unsigned 8-bit or 16-bit raster in a local file. Supported formats are GeoTIFF, ERDAS IMAGINE, ENVI, PNG, JPEG, JPEG 2000, ASCII Grid and BMP. VRT files, web services and database layers are refused. Export them to GeoTIFF first.
- A runtime with 64-bit Python 3.11 or later. All its code must be inside its own folder.
- Free disk space for the output. A 4× enlargement has 16 times as many pixels.

The plugin package has no runtime and no model, and the plugin does not download them. See [Windows only: download the runtime and set it up](#windows-only-download-the-runtime-and-set-it-up).

---

## Getting started

1. Install the plugin from the QGIS Plugin Manager.
2. To install from a plugin ZIP instead, open **Plugins → Manage and Install Plugins → Install from ZIP**. Select the ZIP and install it.
3. Do the steps in [Windows only: download the runtime and set it up](#windows-only-download-the-runtime-and-set-it-up). The model is checked against its expected SHA-256. Before any runtime code runs, the plugin asks you to trust it. The plugin cannot check who made a runtime, so use only a source that you trust. It records every runtime file and blocks processing if one changes. This setup does not install packages into QGIS Python.

---

## Use

1. Open **SR Module for Landsat** from the Raster menu or the toolbar.
2. Select a loaded local raster layer or browse to an input file. A selected file takes precedence over the layer.
3. Choose **Automatic**, **RGB**, or **Monochrome**. Then select the band numbers. Monochrome uses **Red / mono band**.
4. Keep **Use full input bit-depth range** selected, or clear it and enter a display minimum and maximum.
5. Choose the device and a new output path that ends in `.tif` or `.tiff`.
6. Select **OK**. Watch progress, or cancel, in QGIS Tasks.

With **Add output to QGIS** selected, the plugin adds the result to the project when the task ends.

---

## Output and limits

- RGB processing uses the three selected bands. Monochrome output has one gray band. An alpha band is added when the input has alpha, NoData or a mask.
- Display scaling maps the chosen input range to the output integer range. The default range is 0 to 255 for 8-bit data and 0 to 65535 for 16-bit data.
- For 16-bit input, the plugin stretches each tile to its own value range for the model and then maps the result back. A flat tile is stretched at most 16 times, or to its largest value if that value is below one sixteenth of the display range. A few extreme pixels, such as saturated pixels, do not set the stretch. Output values stay on the input scale. An extreme pixel keeps its value, but gets less added detail.
- The plugin does not read Landsat product metadata. It does not apply scale and offset values. It does not mask QA cloud or shadow flags.
- The output TIFF carries its own warning, model hash, scale, source file name and display range.
- The whole image uses one tile grid. How the plugin splits its work does not change the result. The model still sees only 64 × 64 pixels at a time.
- Predictions near NoData and mask edges can show errors.
- Rasters with geolocation arrays or palette (class) bands are refused. So is output that GeoTIFF cannot store without extra files.
- The local-file rule blocks the common ways to reach the network through an input. It is not a network sandbox.
- Large rasters take time and disk space.
- This version ran with the real model on one Windows computer. A full-size Landsat scene was not run. See the release status file in the repository.

---

## Troubleshooting

| Message | What to do |
|---|---|
| SR setup is needed | [Download the runtime ZIP](#windows-only-download-the-runtime-and-set-it-up). Then select `runtime/python.exe` and `weights/real_hat_64.onnx` in **Configure SR runtime and model…**. |
| The runtime files changed | Find out why they changed. Then configure the runtime again. |
| Only local raster files are accepted | Export the layer to a local GeoTIFF. |
| The model worker gave no answer | Try the **cpu** device. Check the message for the worker log. |
| These files already exist | Choose a new output file name. |
| Valid input pixels are outside the selected display range | Widen the display minimum and maximum, or use the full bit-depth range. |
| Select 8-bit or unsigned 16-bit bands of the same data type | Convert the bands to one supported type. |
| DirectML GPU acceleration is unavailable | Choose **auto** or **cpu** as the device. |

---

## For developers

```bash
python3 scripts/package_plugin.py --source landsat_sr --output dist/landsat_sr.zip
python3 scripts/validate_plugin.py landsat_sr --zip dist/landsat_sr.zip
```

Run the tests with the QGIS bindings of your system:

```bash
export QT_QPA_PLATFORM=offscreen
export PYTHONPATH=/usr/share/qgis/python:/usr/lib/python3/dist-packages
/usr/bin/python3 -m pytest -q tests
```

During long GPU tests on an NVIDIA card, run the watchdog in a second window. It stops the model process if the GPU gets too hot:

```powershell
pwsh -File scripts\gpu_watchdog.ps1 -LogPath gpu.csv
```

The file `scripts/release_files.py` lists the allowed files. The validator refuses every other file. Both builders produce the same ZIP bytes for the same input. The QGIS site rejects binary files and ZIPs above 25 MB, so the repository ZIP omits the model and the runtime.

Worker tests need `onnx` and `onnxruntime`. Tests that need missing software skip themselves, so check the skip list with `pytest -rs`.

To build the offline Windows ZIP, give a completed rights record, or mark the build as an internal test:

```bash
python3 scripts/package_offline_windows.py --bundle <folder> --output dist/offline.zip --rights-record <record.json>
python3 scripts/package_offline_windows.py --bundle <folder> --output dist/test.zip --internal-test-build
```

See [model provenance](docs/release/MODEL_PROVENANCE.md) for the open release questions.

---

## Contributing

Open an issue at [github.com/vchhikara/SR-Module-for-Landsat/issues](https://github.com/vchhikara/SR-Module-for-Landsat/issues). Include the QGIS version, the raster type, and the message in the QGIS log.

---

## Author

Vipul Chhikara, India
vipul.chhikara@gmail.com
