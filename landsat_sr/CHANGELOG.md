# Changelog

## 0.7.0

Privacy and input

- The report records only a fixed list of fields, with file names and no folder paths. Logs and messages remove credentials.
- Only local raster files are accepted. VRT files, web services, database layers and virtual paths are refused.

Output

- NaN, infinite or far out-of-range model output stops the run.
- Partial alpha stays partial. Ground control points and RPCs are scaled to the new pixel grid.
- The TIFF carries its own warning and provenance tags.
- The finished GeoTIFF is flushed, closed, read back and compared before publication.
- Publication does not replace existing files. The report is published first and the GeoTIFF last.
- One tile grid covers the whole image, so work splitting no longer changes the result.
- Tiles without any valid pixel skip inference.

Runtime and lifecycle

- The runtime needs your trust once. A later change to any runtime file blocks it.
- The plugin checks for 64-bit Python 3.11 or later and a self-contained runtime.
- The worker runs isolated with a minimal environment, uses pipes without temporary arrays, and stops after a deadline.
- The model is hashed and loaded from the same bytes.
- Unloading the plugin cancels its tasks. Two tasks cannot write the same output.

Packaging

- The validator accepts exactly the release files. Builders refuse links.
- The offline ZIP is reproducible, records a manifest, and needs a rights record or an internal test mark.
- Removed the unused `worker.py` and `onnx_worker.py`.

If you configured a runtime in an earlier version, configure it again to trust it.

## 0.6.3

- Configure a separately supplied Windows inference runtime and model from the Raster menu.
- Check the selected model's SHA-256 before storing its location; continue to support complete offline plugin packages.
- Exercise real RGB and monochrome CPU inference with QGIS 3.44.12 and 4.2.3 on Windows.

## 0.6.2

- Mark the plugin as experimental.

## 0.6.1

- Mark the model worker command as a fixed list of plugin paths for the Bandit scan.
- Mark the public model SHA-256 hash for the secrets scan.

## 0.6.0

- First upload to plugins.qgis.org.
- Use scoped Qt 6 enum names so the plugin loads in QGIS 3.34 and in QGIS 4.
- Check for the offline runtime and model before processing. Show a message when they are missing.
- Add `qgisMaximumVersion`, `repository`, `homepage`, `tracker`, `tags`, `changelog`, and `deprecated` to the metadata.
- Add the GPL-3.0 license file.
- Add package and validation scripts and tests.
