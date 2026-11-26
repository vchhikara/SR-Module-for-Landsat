<h1 align="center">SR Module for Landsat</h1>

<p align="center">
  <img src="docs/images/banner.png" alt="SR Module for Landsat banner: a blocky Landsat scene on the left and a sharper enlarged scene on the right" width="100%">
</p>
<p align="center">
  <strong>Enlarge RGB and monochrome Landsat images four times for clearer display.</strong><br>
  Processing runs offline on your computer. No internet connection and no cloud service.
</p>

<p align="center">
  <img alt="QGIS" src="https://img.shields.io/badge/QGIS-3.34%20to%204.99-589632?logo=qgis&logoColor=white">
  <img alt="Python" src="https://img.shields.io/badge/Python-ONNX%20Runtime-3776AB?logo=python&logoColor=white">
  <img alt="Platform" src="https://img.shields.io/badge/runtime-64--bit%20Windows-0078D4">
  <a href="landsat_sr/LICENSE"><img alt="License: GPL-3.0-or-later" src="https://img.shields.io/badge/license-GPL--3.0--or--later-blue"></a>
</p>

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
| 4× enlargement | Writes a GeoTIFF with 4 times the width and height. The geotransform keeps the same map extent. |
| Input modes | Automatic, RGB, or Monochrome. Choose the band numbers for each color. |
| Display range | Uses the full bit-depth range by default. You can enter a minimum and a maximum. |
| Device choice | Automatic, GPU (DirectML), or CPU. |
| Masks | Pixels that are NoData or masked in the input become transparent in an alpha band. |
| Report | Saves a JSON report next to the output. It lists the settings, the backend, and the invalid pixel count. |
| Safe output | The plugin never replaces an existing GeoTIFF or report. Choose a new name. |

---

## Requirements

- QGIS 3.34 or later. The metadata allows QGIS up to 4.99.
- 64-bit Windows for the bundled offline runtime.
- A prepared unsigned 8-bit or 16-bit raster. Align and prepare the bands first.
- Free disk space for the output. A 4× enlargement has 16 times as many pixels.

The QGIS repository package does not include the inference runtime or model. Obtain a trusted complete Windows x64 runtime package from the maintainer; it contains Python, ONNX Runtime, DirectML and the model. Configure their locations as described below. A separate complete offline plugin package can include them already.

---

## Getting started

1. Install the plugin from the QGIS Plugin Manager, or get the complete offline plugin package from the project maintainer.
2. If using a ZIP, open **Plugins → Manage and Install Plugins → Install from ZIP**.
3. Select the ZIP and install it. If the package does not contain the runtime and model, extract the trusted runtime package to a stable location, then open **Raster → SR Module for Landsat → Configure SR runtime and model…**. Choose `runtime/python.exe` and `weights/real_hat_64.onnx`. The model is checked against its expected SHA-256. This setup does not install packages into QGIS Python.

---

## Use

1. Open **SR Module for Landsat** from the Raster menu or the toolbar.
2. Select a loaded raster layer or browse to an input file. A selected file takes precedence over the layer.
3. Choose **Automatic**, **RGB**, or **Monochrome**. Then select the band numbers. Monochrome uses **Red / mono band**.
4. Keep **Use full input bit-depth range** selected, or clear it and enter a display minimum and maximum.
5. Choose the device and a new output path that ends in `.tif` or `.tiff`.
6. Select **OK**. Watch progress, or cancel, in QGIS Tasks.

With **Add output to QGIS** selected, the plugin adds the result to the project when the task ends.

---

## Output and limits

- RGB processing uses the three selected bands. Monochrome output has one gray band, plus an alpha band when the input has NoData or a mask.
- Display scaling maps the chosen input range to the output integer range. The default range is 0 to 255 for 8-bit data and 0 to 65535 for 16-bit data.
- The plugin does not read Landsat product metadata. It does not apply scale and offset values. It does not mask QA cloud or shadow flags.
- Predictions near NoData and mask edges can show errors.
- Large rasters take time and disk space.
- Real-model CPU inference was tested with small RGB and monochrome rasters on Windows, using QGIS 3.44.12 and 4.2.3. Additional data, hardware and platforms need testing.

---

## Troubleshooting

| Message | What to do |
|---|---|
| SR setup is needed | Obtain the runtime package from the maintainer and select `runtime/python.exe` and `weights/real_hat_64.onnx` in **Configure SR runtime and model…**. |
| Output or its report already exists | Choose a new output file name. |
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

The package script lists the allowed files and produces the same ZIP bytes every time. The QGIS site rejects binary files and ZIPs above 25 MB, so the ZIP omits the model and the runtime.

---

## Contributing

Open an issue at [github.com/vchhikara/SR-Module-for-Landsat/issues](https://github.com/vchhikara/SR-Module-for-Landsat/issues). Include the QGIS version, the raster type, and the message in the QGIS log.

---

## Author

Vipul Chhikara, India
vipul.chhikara@gmail.com
