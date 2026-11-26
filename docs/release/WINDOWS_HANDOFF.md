# Handoff: Windows verification of 0.7.0

Branch: `fix/audit-findings`. Read [the release status](../../RELEASE_TEST_STATUS.md) first.

## State on 2026-11-27

The code fixes are complete and tested on Linux only: QGIS 4.4.0, GDAL 3.12.2, ONNX Runtime on CPU,
with a small test model in place of Real-HAT. In the Linux tool environment, 196 tests passed.
Nothing has run on Windows or with `real_hat_64.onnx`.

The finding IDs in code comments and test names (H-01 to L-03) come from a private audit report.
That report is not in git.

## Rules

- Reproduce a failure first. Add a failing test. Then change the code.
- Report only what you ran. A Linux result does not prove Windows behaviour.
- Do not add co-author or "Generated with" lines to commits.
- Do not commit the runtime, the model or any binary.

## Setup

You need QGIS for Windows, the OSGeo4W shell that comes with it, and the trusted runtime package with
`runtime\python.exe` and `weights\real_hat_64.onnx`.

Run the tests with the QGIS Python. Install `pytest` for it if it is missing. The worker tests also need
`onnx` and `onnxruntime`. Install the test tools in a separate environment. Keep the QGIS installation unchanged.
Use `pytest -rs` and read the skip list. Some tests skip on Windows because they need POSIX features.
The Windows run of these tests is new, so a test itself can be wrong there.

## Tasks, in order

1. **Run the test suite on Windows.**
2. **Check the runtime rule.** In QGIS, open *Configure SR runtime and model* and select the real
   runtime. This is the largest risk. The plugin now refuses a runtime that loads code from outside its
   own folder, and the existing package was never checked against this rule. If it fails, record the
   paths from `sys.path` of `python.exe -I`. Decide whether to fix the package or the rule. Do not
   remove the rule only to make setup pass.
3. **Run the smoke scripts.** Set `LANDSAT_SR_RUNTIME_PACKAGE` to the package folder. Run
   `tests\smoke_qgis_setup.py`, then `tests\smoke_windows_processing.py` with
   `LANDSAT_SR_TEST_DEVICE` set to `cpu`, `auto` and `gpu`. The limit "mean block error below 15" has
   never run with the real model. If it fails, inspect the output before you change the limit.
4. **Check the real model.** The worker now loads the model from bytes in memory. Confirm that the real
   file loads this way. Record the time for each tile on CPU and GPU. The limit for one worker request
   (4 tiles) is 900 seconds.
5. **Inspect a real scene at full size.** Look for lines at tile edges and for artifacts near NoData.
   Include one scene of full Landsat size. Record time, memory and disk use. Compare with 0.6.3.
6. **Check file behaviour:** an existing output, a read-only folder, a nearly full disk, a Unicode path,
   a long path, a network share, and cancel during a run. After a failed run, no `.qgis_sr_*` folder
   and no GeoTIFF must remain.
7. **Check the lifecycle:** disable the plugin and close QGIS while a task runs. No dialog, crash or
   `python.exe` process must remain.
8. **Check supported versions.** Repeat tasks 1 to 3 on the oldest and newest QGIS that you support
   (3.34 with Qt 5 was never tested). If you cannot test a version, narrow `qgisMinimumVersion` or
   `qgisMaximumVersion` in `metadata.txt`.
9. **Test the offline builder** with `--internal-test-build`. Install that ZIP and repeat task 3.
10. **Check CI.** The workflow in `.github/workflows` has never run. It starts after a push.

Update `RELEASE_TEST_STATUS.md` with the results.

## Decisions for the owner

- Confirm the `GPL-3.0-or-later` lines in the source files. **Confirmed on 2026-11-27.**
- Confirm that this repository no longer builds the `RGB SR Module Mono` variant. **Confirmed on 2026-11-27.**
- Close [model provenance](MODEL_PROVENANCE.md) before you share a runtime or model.
