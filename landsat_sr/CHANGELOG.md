# Changelog

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
