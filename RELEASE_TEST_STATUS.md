# SR Module for Landsat 0.6.3 — local test build

The repository-format package contains the plugin source and a configuration dialog. Its runtime and model must still be obtained separately; it does not download them or install Python packages automatically. The existing QGIS repository version is unchanged.

The Windows offline test package contains the plugin, a local Python 3.12 runtime, ONNX Runtime 1.23.0 with DirectML, and the Real-HAT ONNX model. Its model SHA-256 matches the digest in the source. Install this ZIP through QGIS Plugin Manager for a self-contained local test. It is not suitable for QGIS repository upload because it contains binaries.

Checks performed on Windows:

- QGIS 3.44.12 and QGIS 4.2.3: runtime setup dialog, stored settings, menu registration and unload.
- QGIS 3.44.12 and QGIS 4.2.3: real-model CPU inference on synthetic RGB and monochrome GeoTIFFs, including output dimensions and geotransform.
- QGIS 4.2.3: repeated CPU and automatic DirectML GPU inference from the extracted offline ZIP.
- QGIS 3.44.12 and QGIS 4.2.3: 10 package, native GUI and runtime-selection tests passed in each environment.
- Source ZIP structural validation passed.

Before external distribution, verify model provenance and permission to redistribute the converted weights, and review the third-party runtime and library notices. QGIS repository approval rules also prohibit bundled binaries. Users of the QGIS-repository build need a published, trustworthy way to obtain the separate runtime and model; no such download is configured or published by this change. Additional larger rasters, hardware, QGIS versions and platforms need testing.
