# SR Module for Landsat

SR Module for Landsat is an experimental QGIS plugin for enhancing the display of RGB and monochrome raster imagery. It uses the Real-HAT model to produce a 4× enlarged GeoTIFF. Processing runs offline using the bundled runtime and model.

The output is intended for visualization. Fine detail is estimated by a general-purpose, RGB-trained model; it is not verified ground information or a scientifically validated Landsat reflectance or multispectral product. Prepare and align input bands before processing. The plugin does not read Landsat product metadata, apply scale and offset automatically, or mask QA cloud and shadow flags.

## Requirements

- 64-bit Windows and QGIS 3.34 or later.
- A prepared unsigned 8-bit or 16-bit raster, loaded in QGIS or available as a local file.
- Enough disk space for the output: 4× enlargement produces 16 times as many pixels.

The package includes Python, ONNX Runtime, DirectML and the model. Automatic device selection tries DirectML on compatible NVIDIA, AMD and Intel GPUs and falls back to CPU. No internet connection is required to install or run the packaged plugin.

## Installation

1. Obtain the complete packaged plugin ZIP from the project maintainer.
2. In QGIS, open **Plugins → Manage and Install Plugins → Install from ZIP**.
3. Select the ZIP and install it.

This repository contains the plugin source and icon. The offline runtime and model are distributed in the complete plugin ZIP and are required to run it. A source checkout alone is not an installable offline package.

## Use

1. Open **SR Module for Landsat** from the Raster menu or toolbar.
2. Select a loaded raster layer or browse to an input file. A selected file takes precedence over the layer.
3. Choose **Automatic**, **RGB**, or **Monochrome**, then select the relevant band numbers. Monochrome uses **Red / mono band**.
4. Keep **Use full input bit-depth range** selected, or clear it and enter a display minimum and maximum.
5. Choose the device and a new output path ending in `.tif` or `.tiff`.
6. Select **OK**. Monitor progress or cancel the task in QGIS Tasks.

The plugin saves a processing report alongside the output. With **Add output to QGIS** selected, it also adds the result to the project. Choose a different output name if the GeoTIFF or its report already exists.

## Output and limitations

- RGB processing uses the three selected bands. Monochrome output has one grayscale band, with an alpha band when needed for NoData or a mask.
- Display scaling maps the selected input range to the output integer range. The default input range is 0–255 for 8-bit data or 0–65535 for 16-bit data.
- Large rasters are processed in blocks. Processing may take substantial time and disk space.
- Predictions near NoData and mask boundaries can be affected.

## Author

Vipul Chhikara, New Delhi, India · vinod.chhikara@gmail.com

