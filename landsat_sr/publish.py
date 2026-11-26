# SPDX-License-Identifier: GPL-3.0-or-later
"""Publish a GeoTIFF and its report without replacing any existing file.

Two files cannot be renamed in one atomic step. The report is published first
and the GeoTIFF last, so a visible GeoTIFF always has its report. The GeoTIFF
is the commit point. If it fails, the report that this run created is removed.
"""
import os
from pathlib import Path
import shutil

from .constants import SRError

# GDAL reads these next to a raster. A stale one would change the new output.
_SIDECAR_SUFFIXES = ('.aux.xml', '.ovr', '.msk')
_WORLD_SUFFIXES = ('.tfw', '.tifw', '.wld')


def report_path(dest):
    return Path(str(dest) + '.json')


def conflicts(dest):
    """Existing files that block this destination."""
    dest = Path(dest)
    candidates = [dest, report_path(dest)]
    candidates += [Path(str(dest) + suffix) for suffix in _SIDECAR_SUFFIXES]
    candidates += [dest.with_suffix(suffix) for suffix in _WORLD_SUFFIXES]
    return [path for path in candidates if os.path.lexists(path)]


def check_free(dest):
    found = conflicts(dest)
    if found:
        raise SRError('These files already exist: {}. Choose a new output name.'.format(
            ', '.join(path.name for path in found)))


def _fsync(path):
    with open(path, 'rb+') as handle:
        os.fsync(handle.fileno())


def _copy_exclusive(source, target):
    """No-clobber fallback for file systems without hard links."""
    with open(target, 'xb') as out:  # raises FileExistsError, never truncates
        try:
            with open(source, 'rb') as stream:
                shutil.copyfileobj(stream, out, 1024 * 1024)
            out.flush()
            os.fsync(out.fileno())
        except BaseException:
            out.close()
            os.unlink(target)
            raise
    os.unlink(source)


def move_no_clobber(source, target):
    """Move source to target. Fail with FileExistsError if target exists."""
    if os.name == 'nt':
        os.rename(source, target)  # Windows refuses an existing target
        return
    try:
        os.link(source, target)  # atomic on POSIX, refuses an existing target
    except FileExistsError:
        raise
    except OSError:
        _copy_exclusive(source, target)
        return
    try:
        os.unlink(source)
    except OSError:
        pass  # the staging folder is removed afterwards


def publish_pair(staging, report_staging, dest):
    dest = Path(dest)
    report = report_path(dest)
    check_free(dest)
    _fsync(staging)
    _fsync(report_staging)
    try:
        move_no_clobber(report_staging, report)
    except FileExistsError:
        raise SRError('The report file appeared during processing. No file was replaced.') from None
    created = os.stat(report)
    try:
        move_no_clobber(staging, dest)
    except BaseException as exc:
        try:
            if os.path.samestat(os.stat(report), created):  # remove only our own report
                os.unlink(report)
        except OSError:
            raise SRError('Publication failed. Delete the incomplete report file: {}'.format(report.name)) from exc
        if isinstance(exc, FileExistsError):
            raise SRError('The output file appeared during processing. No file was replaced.') from None
        raise
