# SR Module for Landsat 0.7.0 — release status

Version 0.7.0 is **not released**. The results of earlier versions do not apply to it, because the
processing code, worker protocol and runtime setup changed.

## Checked on Linux (2026-11-27)

QGIS 4.4.0 (Qt 6), GDAL 3.12.2, Python 3.14, ONNX Runtime on CPU. The tests use real GDAL, the real
QGIS task manager, the real worker process and real ONNX Runtime. A small test model that repeats
pixels stands in for Real-HAT. See the test folder for the cases.

## Not checked

- The real `real_hat_64.onnx` model: pixel quality, speed, and loading it from memory.
- Windows: runtime trust and self-containment check on the real runtime package, DirectML, file
  publication, junctions, long paths, network shares and antivirus locks.
- QGIS 3.34 and 3.44 with this version, and any Qt 5 build.
- A real full disk or a failing network share.
- The CI workflow in `.github/workflows` (it runs after a push).
- Scenes of full Landsat size: time, memory and disk use.

## Before release

1. On Windows, run `tests/smoke_qgis_setup.py` and `tests/smoke_windows_processing.py` with each device
   (`cpu`, `auto`, `gpu`) on the oldest and newest QGIS that you support.
2. Look at a real scene at full size for seams and edge artifacts.
3. If a supported QGIS version fails or stays untested, narrow `qgisMinimumVersion` or `qgisMaximumVersion`.
4. Close every item in `docs/release/MODEL_PROVENANCE.md` before you distribute a runtime or model.
