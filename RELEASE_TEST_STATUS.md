# SR Module for Landsat 0.7.0 — release status

Version 0.7.0 is **not released**. The results of earlier versions do not apply to it, because the
processing code, worker protocol and runtime setup changed. The Windows tests below passed on one
computer. [Not checked](#not-checked) and [Before release](#before-release) list what remains.

## Test computer and runtime (2026-11-27)

Windows 11, QGIS 4.2.0 (Qt 6), GDAL 3.13.1, Python 3.12.13. Intel Core i5-11300H, 23.8 GB RAM, NVIDIA
GeForce GTX 1650 (4 GB).

The runtime and model came from `landsat_sr_0.6.3_windows_offline.zip` in the draft GitHub release
`v0.6.3` (SHA-256 `3a9630588e2b497d7039f77c10741668d6652ae065920dea9734d1a40fae7926`, checked). The
runtime has Python 3.12.10, NumPy 2.2.6 and ONNX Runtime 1.23.0 with DirectML and CPU. The model
SHA-256 matches `3f47670dfeba712d68cd479f11cfe25866453c08b840269102b7a037eebc8908`.

## Handoff tasks

| Task | Result |
|---|---|
| 1. Test suite | Passed: 194 passed, 11 skipped |
| 2. Runtime rule | Passed. The existing runtime is self-contained. The rule was not changed |
| 3. Smoke scripts | Passed on `cpu`, `auto` and `gpu` |
| 4. Real model | Passed. It loads from memory |
| 5. Real scene | Done on crops of a real scene. A full scene was **not** run |
| 6. File behaviour | Passed, except a nearly full disk and a remote share, which were not checked |
| 7. Lifecycle | Passed in the QGIS application |
| 8. Versions | Range narrowed to QGIS 4.2 |
| 9. Offline builder | Passed with `--internal-test-build` |
| 10. CI | The first run failed. It is fixed. See [CI](#ci) |

### Task 1: test suite

The test tools were in a separate virtual environment, made from `apps\Python312\python.exe` with
`--system-site-packages` and with the user site disabled. It held ONNX Runtime 1.32.0 (CPU only) and
ONNX 1.23.2. The QGIS installation was not changed. These tests skipped on Windows:

| Count | Test location | Reason |
|---|---|---|
| 6 | `test_runtime_config.py` (lines 98, 120, 132) | uses a shell script as a fake interpreter |
| 2 | `test_engine.py:435` | reads open handles from `/proc` |
| 1 | `test_engine.py:462` | needs POSIX permissions |
| 2 | `test_package.py:167` | symlinks need privileges on Windows |

Notes: `bin\python.exe` of QGIS did not start with `-I`. With `python-qgis.bat`, ONNX Runtime came
from the user site, which `-I` hides. The GPU error test used the CPU-only ONNX Runtime.

### Tasks 2 to 4: runtime, smoke scripts, real model

`sys.path` of the runtime `python.exe -I` had only `runtime\python312.zip`, `runtime` and
`runtime\Lib\site-packages`. `smoke_qgis_setup.py` passed through the real configure dialog.

`smoke_windows_processing.py` passed all four cases on each device. `auto` and `gpu` used DirectML.
The mean block error was 1.08 to 2.50 on each device, below the limit of 15. These cases use 8-bit
data.

| Device | Start and load | One request (4 tiles), median | Per tile |
|---|---|---|---|
| DirectML GPU | 2.6 s | 1.39 s | 0.35 s |
| CPU | 1.5 s | 7.90 s | 1.98 s |

The limit for one request is 900 s.

### Task 5: real scene

Scene: `LC09_L2SP_145039_20251123_20251124_02_T1`, surface reflectance stack, 7711 × 7841, UInt16,
NoData 0, about 33% NoData. At the owner's request, only crops ran, with RGB bands 3, 2, 1.

**Fixed defect: 16-bit imagery was destroyed.** With the default range of 0 to 65535, land values of
about 7000 to 10000 reached the model with almost no contrast. The output was smeared, had shifted
colours and at the NoData edge did not match the terrain. Version 0.6.3 did the same on the same
crop. The 8-bit smoke scripts did not show it. Each 16-bit tile is now stretched to its own range for
the model, at most 16 times, and mapped back. Output values stay on the input scale. NoData pixels
now reach the model as the tile mean, and not as black.

1024 × 1024 crop with a NoData edge (25% NoData), DirectML GPU. The block error is the difference
between each 4 × 4 output block mean and its input pixel, in digital numbers (DN):

| Version | Time | Peak memory, QGIS side / worker | Peak disk use | Block error, all / near NoData | Correlation |
|---|---|---|---|---|---|
| 0.6.3 | 273 s | 387 / 589 MB | 72 MB | 341 / 693 DN | 0.875 |
| 0.7.0 before the fix | 137 s | 423 / 714 MB | 68 MB | 343 / 685 DN | 0.872 |
| 0.7.0 with the fix | 136 s | 426 / 715 MB | 65 MB | 125 / 204 DN | 0.980 |

"Near NoData" is within 8 input pixels. The alpha band matched the input mask in every output pixel.
Tile-stride lines had a jump ratio of 1.07 (vertical) and 1.05 (horizontal). Other line offsets
ranged from 0.94 to 1.08. The tile lines ranked 3rd and 4th of 48, so a weak effect at tile lines is
possible. A visual check of two 400 × 400 output windows (one at the NoData edge) showed no visible
seam or edge artifact with the fix. The whole crop was not inspected by eye.

A 256 × 256 window was used to choose the stretch limit. Limits of 16 and 64 gave the same block
error (91 to 92 DN). A limit of 8 gave 119 DN. This tuning used one window of one scene.

**Not run: a full scene.** These are estimates from the crop, not measurements: about 2 hours on this
GPU, about 10 hours on this CPU, and an output file of about 4 GB.

The model is a general RGB model. It adds estimated detail. A low block error does not show that the
added detail is real.

### Task 6: file behaviour

These cases used the real engine, the real worker process and the small test model, with CPU
inference, outside the QGIS application. A scratch script ran them. It is not in git.

| Case | Result |
|---|---|
| Normal run | Success, exact pixels, only the GeoTIFF and report remain |
| Existing output | Refused, original file unchanged |
| Unicode folder name | Success, exact pixels |
| Output path of 356 characters, `LongPathsEnabled` = 1 | Success, exact pixels |
| Output on the local share `\\localhost\C$` | Success, and cancel left no files |
| Cancel after the first progress call | `Cancelled.`, no files remain |
| Forced read-back failure | Error shown, no files remain |
| Folder with a deny rule for new files and folders | Error shown, no files remain |

These ran before the 16-bit change. The automated tests ran again after it.

**Fixed defect: endless task on a read-only folder.** `tempfile.mkdtemp` kept retrying when the folder
denied new folders. The engine did not return in 90 seconds. It now shows "Cannot write to the output
folder".

**Fixed defect: output permissions.** The published GeoTIFF and report did not inherit the folder
permissions. Only SYSTEM, Administrators and OWNER RIGHTS had access. The cause was the private
staging folder, because a rename keeps the access list of a file. The staging folder stays private,
because it holds the worker log and is the Python cache prefix of the worker. After publication, the
plugin resets only the two published files so that they inherit from the output folder. If that step
fails, the output is kept and the plugin shows a warning. In the success cases, including the long
path and the UNC path, the GeoTIFF then had only inherited entries.

### Task 7: lifecycle

The installed offline package ran in the QGIS application with a separate profile:

- A full run through the processing dialog loaded a valid 640 × 640 layer.
- Disabling the plugin during a task took 0.3 s. No dialog, worker process or staging file remained.
- Closing QGIS during a task showed the QGIS "Active Tasks" question. After "Yes", the task ended with
  no plugin dialog and no worker. A second close then exited QGIS. A control with a dummy task and no
  plugin work also needed the second close. No staging file, worker or new QGIS crash dump remained.

**Fixed defect.** A cancelled task showed a modal "Cancelled." box. During a close, it appeared after
the QGIS question, and QGIS was still running when the test ended. A cancelled task now shows a
message bar note.

### Task 8: supported versions

Only QGIS 4.2.0 was tested on Windows. At the owner's decision, `metadata.txt` now has
`qgisMinimumVersion=4.2` and `qgisMaximumVersion=4.2`. QGIS reads this as 4.2.0 to 4.2.99. Versions
4.2.1 and later were not tested.

### Task 9: offline builder

`package_offline_windows.py --internal-test-build` made a 128 MB ZIP with `DO_NOT_DISTRIBUTE.txt`.
The ZIP was extracted into the plugin folder of a new profile. "Install from ZIP" in the QGIS user
interface was not used. The bundled trust record matched the installed runtime. The processing smoke
script passed on all three devices from the installed copy.

## CI

[Run 45880597343](https://github.com/vchhikara/SR-Module-for-Landsat/actions/runs/45880597343) on
`71096ac` failed, because `tests/test_worker.py` needed GDAL at test collection. After the fix,
[run 45888243800](https://github.com/vchhikara/SR-Module-for-Landsat/actions/runs/45888243800) on
`530212f` passed in all five jobs. See the Actions page for later commits.

The `qgis` jobs run on Linux containers without ONNX Runtime. They run the fake-worker tests, but not
the real worker with ONNX Runtime. They include QGIS 3.34, which the plugin no longer declares.

## Checked on Linux (2026-11-27, before these changes)

QGIS 4.4.0 (Qt 6), GDAL 3.12.2, Python 3.14, ONNX Runtime on CPU, with a small test model.

## Not checked

- A full-size Landsat scene: time, memory, disk use and visual quality.
- Visual quality on other scenes, sensors, monochrome 16-bit data and water or snow areas.
- A nearly full disk, a remote network share, a network failure, junctions and antivirus locks.
- Long paths with `LongPathsEnabled` = 0.
- Cancel with the button in the QGIS task list. The tests call the same task `cancel` method.
- "Install from ZIP" in the QGIS user interface.
- DirectML on other GPUs.
- QGIS versions other than 4.2.0 on Windows.

## Before release

1. Run one full-size scene and inspect it.
2. Close every item in `docs/release/MODEL_PROVENANCE.md` before you distribute a runtime or model.
3. Confirm the `GPL-3.0-or-later` lines in the source files.
4. Confirm that this repository no longer builds the `RGB SR Module Mono` variant.
