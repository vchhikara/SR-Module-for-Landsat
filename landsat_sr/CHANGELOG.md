# Changelog

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
