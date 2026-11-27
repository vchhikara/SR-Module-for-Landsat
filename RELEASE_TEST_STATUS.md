# SR Module for Landsat 0.7.0 release status

Version 0.7.0 was **released** on 2026-11-27 as
[v0.7.0](https://github.com/vchhikara/SR-Module-for-Landsat/releases/tag/v0.7.0). The release holds the
runtime and model ZIP only.
The Windows tests
below ran on one computer. [Not checked](#not-checked) and [Open items](#open-items) list what remains.

Until [Release commit](#release-commit), the sections below describe tests of earlier commits.

## Test computer and runtime (2026-11-27)

Windows 11, QGIS 4.2.0 (Qt 6), GDAL 3.13.1, Python 3.12.13. Intel Core i5-11300H, 23.8 GB RAM, NVIDIA
GeForce GTX 1650 (4 GB).

## Handoff tasks

| Task               | Result                                                                                                                                                |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Test suite      | Passed: 200 passed, 11 skipped                                                                                                                        |
| 2. Runtime rule    | Passed. The existing runtime is self-contained. The rule was not changed                                                                              |
| 3. Smoke scripts   | Passed on `cpu`, `auto` and `gpu`                                                                                                                     |
| 4. Real model      | Passed. It loads from memory                                                                                                                          |
| 5. Real scene      | Done on crops of a real scene. A full scene was **not** run                                                                                           |
| 6. File behaviour  | Passed, except a nearly full disk and a remote share, which were not checked. A real disk test needs a small volume, which needs administrator rights |
| 7. Lifecycle       | Passed in the QGIS application                                                                                                                        |
| 8. Versions        | Range narrowed to QGIS 4.2                                                                                                                            |
| 9. Offline builder | Passed as an internal test build and with a rights record. The "Install from ZIP" page passed                                                         |
| 10. CI             | The first run failed. It is fixed. See [CI](#ci)                                                                                                      |

### Task 1: test suite

The test tools were in a separate virtual environment, made from `apps\Python312\python.exe` with
`--system-site-packages` and with the user site disabled. It held ONNX Runtime 1.32.0 (CPU only) and
ONNX 1.23.2. The QGIS installation was not changed. These tests skipped on Windows:

| Count | Test location                                 | Reason                                    |
| ----- | --------------------------------------------- | ----------------------------------------- |
| 6     | `test_runtime_config.py` (lines 98, 120, 132) | uses a shell script as a fake interpreter |
| 2     | `test_engine.py:435`                          | reads open handles from `/proc`           |
| 1     | `test_engine.py:462`                          | needs POSIX permissions                   |
| 2     | `test_package.py:167`                         | symlinks need privileges on Windows       |

Notes: `bin\python.exe` of QGIS did not start with `-I`. With `python-qgis.bat`, ONNX Runtime came
from the user site, which `-I` hides. The GPU error test used the CPU-only ONNX Runtime.

### Tasks 2 to 4: runtime, smoke scripts, real model

`sys.path` of the runtime `python.exe -I` had only `runtime\python312.zip`, `runtime` and
`runtime\Lib\site-packages`. `smoke_qgis_setup.py` passed through the real configure dialog.

`smoke_windows_processing.py` passed all five cases on each device. `auto` and `gpu` used DirectML.
For the four 8-bit cases, the mean block error was 1.08 to 2.50, below the limit of 15.

The first four cases did not find the 16-bit defect in task 5. A fifth case, `rgb_uint16`, was added.
It uses 16-bit values in a narrow range, with a limit of 240 (15 times its value scale). The current
code gave 40.01 on each device. With the engine of `b730865`, the case failed on `gpu` with 527.69.

| Device       | Start and load | One request (4 tiles), median | Per tile |
| ------------ | -------------- | ----------------------------- | -------- |
| DirectML GPU | 2.6 s          | 1.39 s                        | 0.35 s   |
| CPU          | 1.5 s          | 7.90 s                        | 1.98 s   |

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

| Version              | Time  | Peak memory, QGIS side / worker | Peak disk use | Block error, all / near NoData | Correlation |
| -------------------- | ----- | ------------------------------- | ------------- | ------------------------------ | ----------- |
| 0.6.3                | 273 s | 387 / 589 MB                    | 72 MB         | 341 / 693 DN                   | 0.875       |
| 0.7.0 before the fix | 137 s | 423 / 714 MB                    | 68 MB         | 343 / 685 DN                   | 0.872       |
| 0.7.0 with the fix   | 136 s | 426 / 715 MB                    | 65 MB         | 125 / 204 DN                   | 0.980       |

"Near NoData" is within 8 input pixels. The alpha band matched the input mask in every output pixel.
Tile-stride lines had a jump ratio of 1.07 (vertical) and 1.05 (horizontal). Other line offsets
ranged from 0.94 to 1.08. The tile lines ranked 3rd and 4th of 48, so a weak effect at tile lines is
possible. A visual check of two 400 × 400 output windows (one at the NoData edge) showed no visible
seam or edge artifact with the fix. The whole crop was not inspected by eye.

A 256 × 256 window was used to choose the stretch limit. Limits of 16 and 64 gave the same block
error (91 to 92 DN). A limit of 8 gave 119 DN. This tuning used one window of one scene.

### Task 5 continued: small windows of different terrain

Twenty windows of 256 x 256 input pixels ran on the DirectML GPU, with the engine of `b730865` and with
the fixed engine. Sources: Landsat 9 L2SP path 145 row 39, Landsat 8 path 147 row 41 and path 143 row 41,
Cartosat-1 PAN (10 bits per pixel) and one 8-bit Sentinel-2 RGB file. All are real imagery.

**Fixed defect: data with small values in a 16-bit file.** The Cartosat window uses values of about 60 to 170. After the first 16-bit fix, its output was still black. The minimum stretch was one sixteenth of
0 to 65535, which is far above these values. For a tile whose largest value is below that minimum, the
minimum span is now the largest value. The other 19 windows gave the same numbers before and after.

The table gives the block error divided by the standard deviation of the input window (lower is better),
then the correlation:

| Window content                                     | `b730865`                     | Fixed                         |
| -------------------------------------------------- | ----------------------------- | ----------------------------- |
| Snow and ice                                       | 0.08 / 0.994                  | 0.07 / 0.996                  |
| Dense forest                                       | 1.26 / 0.373                  | 0.20 / 0.979                  |
| Deep terrain shadow                                | 0.30 / 0.942                  | 0.11 / 0.987                  |
| Cloud, Himalaya                                    | 0.10 / 0.993                  | 0.09 / 0.995                  |
| Rugged relief                                      | 0.06 / 0.996                  | 0.05 / 0.997                  |
| Path 147: seven windows of haze or cloud           | 0.11 to 2.00 / 0.641 to 0.996 | 0.05 to 0.22 / 0.990 to 0.999 |
| Path 143: three windows (rivers, hills, dark area) | 0.44 to 2.60 / 0.158 to 0.877 | 0.09 to 0.21 / 0.965 to 0.993 |
| Mono 15 m pan, haze                                | 1.42 / 0.956                  | 0.08 / 0.996                  |
| Mono NIR, snow                                     | 0.08 / 0.994                  | 0.07 / 0.995                  |
| Mono NIR, haze                                     | 1.46 / 0.938                  | 0.08 / 0.996                  |
| Mono Cartosat, built-up area                       | 1.86 / 0.106                  | 0.15 / 0.977                  |
| Sentinel-2, 8-bit RGB                              | 0.08 / 0.993                  | 0.07 / 0.994                  |

In the fixed outputs, the tile-line jump ratio was inside the range of the other line offsets in every
window. Alpha matched the input mask where the output had alpha. A 384 x 384 part of each output was
inspected by eye. It agreed with its input in all 20 windows. The cloud and haze windows have weak fine
detail (detail correlation as low as 0.58). The Path 147 scene showed no clear ground in these windows,
so desert, city and open water of that scene were not tested.

### Task 6: file behaviour

These cases used the real engine, the real worker process and the small test model, with CPU
inference, outside the QGIS application. A scratch script ran them. It is not in git.

| Case                                                  | Result                                                    |
| ----------------------------------------------------- | --------------------------------------------------------- |
| Normal run                                            | Success, exact pixels, only the GeoTIFF and report remain |
| Existing output                                       | Refused, original file unchanged                          |
| Unicode folder name                                   | Success, exact pixels                                     |
| Output path of 356 characters, `LongPathsEnabled` = 1 | Success, exact pixels                                     |
| Output on the local share `\\localhost\C$`            | Success, and cancel left no files                         |
| Cancel after the first progress call                  | `Cancelled.`, no files remain                             |
| Forced read-back failure                              | Error shown, no files remain                              |
| Folder with a deny rule for new files and folders     | Error shown, no files remain                              |

| Input and output folder reached through a junction | Success, exact pixels |

All cases in this table, with the junction case, ran again on the final engine and publication code.

**Fixed defect: a short file lock lost the whole run.** A program such as a virus scanner can hold a
new file for a moment. With a staging file held for 1 s, publication failed with `PermissionError`.
With a 1 s lock during cleanup, the `.qgis_sr_*` folder stayed. The plugin now tries the rename and
the cleanup again for about 6 s. Tests in `tests/test_publish.py` hold a real file, and they failed
before the fix. A lasting refusal still fails, publishes nothing and takes about 6 s longer. A lock
that lasts longer than that still loses the run. No real antivirus product was tested.

**Junctions in the runtime folder.** A junction to files outside the folder is refused. A junction
loop inside it ended in 0.3 s. A junction to an empty outside folder does not change the fingerprint.
These were probes with a scratch script.

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

`package_offline_windows.py --internal-test-build` made a 128 MB ZIP.
The QGIS installer function behind "Install from ZIP" (`installFromZipFile`) installed it into a new
profile. A script called it, so the file chooser was not used. The plugin became active and loaded
from the new profile. The bundled trust record matched the installed runtime. All five smoke cases
passed on `cpu`, `auto` and `gpu` from this installed copy.

After the last engine change at that time (commit `0fa5325`), the ZIP was built again. It installed into a fresh
profile in the same way. The three task 7 cases then passed from that installed copy: no worker process
or staging folder remained, and there was no new QGIS crash dump.

**"Install from ZIP" page.** The last ZIP (SHA-256
`199ec7d02745a1748f7069967f332254b720907c3e08975b31f01d80807b307d`) was then installed through the QGIS
Plugin Manager in another new profile. A test script clicked the real browse button. A second script
typed the ZIP path into the Windows file chooser and sent a click to its Open button. The test script
then clicked the real install button and answered "Yes" to the QGIS security warning. The plugin became
active, loaded from the new profile, and its runtime matched the trust record. The clicks were
automated. Nobody did them by hand, and no folder browsing in the chooser was tested.

**Cancel in the QGIS task list.** A test script opened the task list from the status bar and clicked the
status column of the running task. The task ended 9.3 s after the click. No dialog, worker process, output
file, staging file or map layer remained, and there was no new QGIS crash dump.

## GPU safety during tests

`scripts/gpu_watchdog.ps1` reads `nvidia-smi` and stops the plugin's model process before the GPU gets too
hot. It changes no GPU setting. A trip test with a 1 C limit stopped only the matching test processes. An
unrelated Python process stayed alive. It was not tested with a really hot GPU. In a monitored part of
the later tests (195 readings), the peak was 70 C, with no hardware slowdown and no trip. Earlier runs
were not monitored. During the two repeats of task 7, the peak was 58 C, with no trip. The plugin itself
does not start the watchdog.

## CI

The first run, on `dad32a6`, failed, because `tests/test_worker.py` needed GDAL at test collection. After
the fix, the run on `2cde131` passed in all five jobs. A later run, after the change to QGIS 4.2, also
passed: `lint-and-package` 123 passed, 5 skipped; `windows` 117 passed, 11 skipped; each `qgis` job 188
passed, 11 skipped.

On the release commit `3c91351`, all five jobs passed in the runs for
[`main`](https://github.com/vchhikara/SR-Module-for-Landsat/actions/runs/45947419358),
[`fix/audit-findings`](https://github.com/vchhikara/SR-Module-for-Landsat/actions/runs/45947419360) and
the [`v0.7.0` tag](https://github.com/vchhikara/SR-Module-for-Landsat/actions/runs/45947441695).

## Review changes after the Windows tests

A later review changed these points on Linux. [Release commit](#release-commit) gives the Windows tests
that ran after these changes.

- 16-bit stretch: a few extreme pixels no longer set the range of a tile. The range may pass the 1st and
  99th percentile by at most the distance between them. Where no pixel lies beyond that limit, the model
  input is the same as in the Windows tests. Where pixels lie beyond it, the model input differs. What the
  limit removes is added back to the output without enhancement. This was tested only with test models.
- Publication without hard links no longer fails if the staging file cannot be deleted.
- A real error is shown also if the task was cancelled.
- The GPU watchdog now trips if `nvidia-smi` fails or returns nothing. The Windows CI job tests this with
  a replacement `nvidia-smi`, not with a GPU.

## Release commit

These tests ran on Windows on 2026-11-27, with the files of commit `3c91351`. At the time of the tests,
the commit had a different ID. The file tree is identical.

**Test suite:** 212 passed, 13 skipped, with the QGIS Python. The skips are 6 for the shell-script fake
interpreter, 2 for `/proc`, 1 for POSIX permissions, 2 for symlink rights and 2 for the non-Windows hard
link fallback. `mypy` did not run on this computer. CI runs it.

**Smoke scripts:** all five cases passed on `cpu`, `auto` and `gpu`, with block errors of 2.17, 1.08,
2.50, 1.99 and 40.01 on each.

**1024 × 1024 crop:** block error 122 DN overall and 202 DN near NoData, correlation 0.981, 138 s. The
engine before the review changes gave 125 DN, 204 DN and 0.980 in 137 s. The new stretch limit acted in
51 of 350 tiles.

**Bright spots:** three 256 × 256 windows with clipped bright pixels had a lower block error than before
the review changes, both overall and at the clipped pixels. Areas that no affected tile covers were
identical. **Known visual effect:** in one window, a very bright spot shows visible 4 × 4 blocks in its
core. The earlier engine was smooth there, but matched the input colour less well. The probable cause is
that the removed part is added back at input resolution. Only the strongest spot of each window was
enlarged.

**20 small terrain windows:** 16 outputs were identical to the earlier fixed outputs. The other 4 changed,
with the same or slightly better block error and correlation. Nobody inspected the new outputs by eye.

**Runtime ZIP:** `landsat_sr_runtime_windows_x64.zip`, 127,879,408 bytes, SHA-256
`54b502d8ef1d38f5995f534fe86647e0a3b8ca034e2a9d0046c9929917d0f9d8`.

- The rights record passed the builder check. The model hash matched. The 1254 runtime and model files
  are identical to those in the 0.6.3 download. All 1262 manifest entries matched, also after the tests.
- In a new QGIS profile, a ZIP of the plugin without runtime or model installed through the "Install
  from ZIP" page. The configure dialog accepted the extracted runtime. A 160 × 160 real crop then ran through the plugin dialog on `cpu` (21 s) and `auto` (8 s, DirectML). Clicks and typed paths were
  automated.
- All five smoke cases passed on `cpu`, `auto` and `gpu` with the extracted runtime.
- GitHub reported the same size and SHA-256 for the published file. A request without sign-in returned the same size.

The GPU watchdog did not trip. The highest peak in these tests was 79 °C.

## Checked on Linux (2026-11-27, before these changes)

QGIS 4.4.0 (Qt 6), GDAL 3.12.2, Python 3.14, ONNX Runtime on CPU, with a small test model.

## Not checked

- A full-size Landsat scene: time, memory, disk use and visual quality.
- Visual quality on desert, large open water, and sensors other than those listed in task 5.
- A nearly full disk, a remote network share, a network failure and real antivirus products.
- Long paths with `LongPathsEnabled` = 0.
- DirectML on other GPUs.
- QGIS versions other than 4.2.0 on Windows.

## Open items

0.7.0 was released with these items open.

1. Run one full-size scene and inspect it.
2. Steps 2 and 3 of `docs/release/MODEL_PROVENANCE.md` (conversion script and numeric comparison) are open. The owner completed the rights record without them.
3. Build and test the offline package from the release commit. The offline ZIP described under task 9 was built before the review changes.