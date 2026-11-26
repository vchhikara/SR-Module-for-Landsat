# SR Module for Landsat 0.7.0 — release status

Version 0.7.0 is **not released**. The results of earlier versions do not apply to it, because the
processing code, worker protocol and runtime setup changed.

## Checked on Linux (2026-11-27)

QGIS 4.4.0 (Qt 6), GDAL 3.12.2, Python 3.14, ONNX Runtime on CPU. The tests use real GDAL, the real
QGIS task manager, the real worker process and real ONNX Runtime. A small test model that repeats
pixels stands in for Real-HAT. See the test folder for the cases.

## Checked on Windows (2026-11-27)

Commit `71096ac` plus the changes in this section, in "CI" and in "File behaviour". Windows 11, QGIS 4.2.0 (Qt 6), GDAL 3.13.1,
Python 3.12.13, NumPy 2.4.6. The test tools were in a separate virtual environment, made from
`apps\Python312\python.exe` with `--system-site-packages` and with the user site disabled. It held
ONNX Runtime 1.32.0 (CPU only) and ONNX 1.23.2. The QGIS installation was not changed.

Final result of `pytest -rs`: **186 passed, 11 skipped**. This includes one new test. The worker tests ran. These tests skipped:

| Count | Test location | Reason |
|---|---|---|
| 6 | `test_runtime_config.py` (lines 98, 120, 132) | uses a shell script as a fake interpreter |
| 2 | `test_engine.py:435` | reads open handles from `/proc` |
| 1 | `test_engine.py:462` | needs POSIX permissions |
| 2 | `test_package.py:167` | symlinks need privileges on Windows |

The first run had 1 failure, in `test_a_failure_shows_a_redacted_message`. On this QGIS build,
`QgsMessageLog.messageReceived` did not fire, also for a direct `logMessage` call.
`messageReceivedWithFormat` did fire. The test now uses the newer signal when it exists.

Notes for this setup:

- `bin\python.exe` of QGIS did not start with `-I`.
- With `python-qgis.bat`, ONNX Runtime came from the user site, which `-I` hides.
- The GPU test used the CPU-only ONNX Runtime. It shows the error without DirectML. It does not
  test DirectML.

## CI

[Run 45880597343](https://github.com/vchhikara/SR-Module-for-Landsat/actions/runs/45880597343)
on `71096ac` **failed**.

- `lint-and-package` and `windows` failed at test collection. `tests/test_worker.py` imported
  `landsat_sr.engine`, which needs `osgeo`. Ruff and Bandit passed. The package and validator steps
  did not run.
- `qgis` passed on `release-3_34`, `ltr` and `latest` (Linux containers): 181 passed, 9 skipped in
  each. The containers have no ONNX Runtime, so the tests that need it skipped: `test_worker.py`
  (lines 49, 61, 66 and 80, and two skips from `conftest.py:46`) and `test_stream_worker.py`. The
  fake-worker tests for deadlines, cancel, broken replies, redaction and the child environment ran.
  These jobs do not test the real worker with ONNX Runtime.

The import now is inside the one test that needs GDAL. A local environment (Windows, Python 3.12
from python.org, no GDAL) showed the same collection error before the change. After the change it
gave 114 passed, 11 skipped. Ruff, Bandit, `package_plugin.py` and `validate_plugin.py` passed there.
**CI has not run with these changes.**

## File behaviour (task 6, partial)

These cases used the real engine, the real worker process and the small test model, with CPU
inference, outside the QGIS application. They ran before tasks 2 to 5, which need the runtime
package. A scratch script ran them. It is not in git.

| Case | Result with the fix |
|---|---|
| Normal run | Success, exact pixels, only the GeoTIFF and report remain |
| Existing output | Refused, original file unchanged |
| Unicode folder name | Success, exact pixels |
| Output path of 356 characters, `LongPathsEnabled` = 1 | Success, exact pixels |
| Cancel after the first progress call | `Cancelled.`, no files remain |
| Forced read-back failure | Error shown, no files remain, so no open handle blocked the cleanup |
| Folder with a deny rule for new files and folders | Error shown, no files remain |

**Fixed defect.** Before the fix, the deny-rule case did not return in 90 seconds, and the process
was killed. `tempfile.mkdtemp` received `PermissionError`, `os.access` reported the folder as
writable, and `mkdtemp` was still retrying after 20000 calls. Its limit is 2147483647. `engine.py`
now makes one attempt and shows "Cannot write to the output folder". The new test failed before the
fix. This case ran in the engine only, not in the QGIS application.

**Open defect: output permissions.** This defect is in `71096ac`. It was seen in a normal run with
the original `mkdtemp` code, and the fix above does not change it. A file made in the work folder
inherited the folder permissions. The published GeoTIFF and report did not. Their access list had
only SYSTEM, Administrators and OWNER RIGHTS. The cause is the staging folder mode. A separate
probe with the Python 3.12.13 of this QGIS moved a file out of a new folder. With mode `0o700`, the
file kept the restricted access list. With mode `0o777`, it had the inherited permissions. Other
Python builds were not tested. Other users of a shared folder may be unable to read the output.
The fix above keeps mode `0o700`. The staging folder also holds the worker log and is the Python
cache prefix of the worker. `-B` stops cache writes, but not cache reads. Thus do not loosen the
staging folder without a security review. One option is to restore inheritance on the two published
files only.

The normal run and the cancel run also passed with the output folder on the local administrative
share `\\localhost\C$` (input on the local disk). This checks a UNC path on the same computer. It
does not test a remote server or a network failure.

Not checked for task 6: a nearly full disk, a remote network share, and cancel from the QGIS task
list.

## Blocked: no runtime package

A search of drives C: and E: found no `real_hat_64.onnx` other than small test files in pytest
temporary folders. Handoff tasks 2 to 5, task 7 and task 9 did not run. They need the trusted package with
`runtime\python.exe` and `weights\real_hat_64.onnx` (SHA-256
`3f47670dfeba712d68cd479f11cfe25866453c08b840269102b7a037eebc8908`).

Task 8 is open. The search of `C:\Program Files` found only QGIS 4.2.0. `metadata.txt` was not changed.

## Not checked

- The real `real_hat_64.onnx` model: pixel quality, speed, and loading it from memory.
- Windows: runtime trust and self-containment check on the real runtime package, DirectML,
  junctions, remote network shares and antivirus locks. Long paths with `LongPathsEnabled` = 0.
- The smoke scripts, and plugin disable or QGIS close during a task in the QGIS application.
- QGIS 3.34 and 3.44 with this version on Windows, and any Qt 5 build on Windows.
- A real full disk or a failing network share.
- Scenes of full Landsat size: time, memory and disk use.

## Before release

1. On Windows, run `tests/smoke_qgis_setup.py` and `tests/smoke_windows_processing.py` with each device
   (`cpu`, `auto`, `gpu`) on the oldest and newest QGIS that you support.
2. Look at a real scene at full size for seams and edge artifacts.
3. If a supported QGIS version fails or stays untested, narrow `qgisMinimumVersion` or `qgisMaximumVersion`.
4. Close every item in `docs/release/MODEL_PROVENANCE.md` before you distribute a runtime or model.
