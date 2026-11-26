# SPDX-License-Identifier: GPL-3.0-or-later
"""Publish a GeoTIFF and its report without replacing any existing file.

Two files cannot be renamed in one atomic step. The report is published first
and the GeoTIFF last, so a visible GeoTIFF always has its report. The GeoTIFF
is the commit point. If it fails, the report that this run created is removed.
"""
import os
from pathlib import Path
import shutil
import time

from .constants import SRError

# GDAL reads these next to a raster. A stale one would change the new output.
_SIDECAR_SUFFIXES = ('.aux.xml', '.ovr', '.msk')
_WORLD_SUFFIXES = ('.tfw', '.tifw', '.wld')
# A virus scanner or indexer can hold a new file for a moment. Windows then refuses to rename or
# delete it. The plugin waits about 6 seconds in total before it gives up.
_RETRY_DELAYS = (0.1, 0.2, 0.4, 0.8, 1.6, 3.2)


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


def inherit_permissions(path):
    """Windows only: give a moved file the permissions that its folder gives to a new file.

    The staging folder is private, and a rename keeps the access list of the file. This does
    the same as "icacls /reset": no entries of its own, inheritance on.
    """
    import ctypes
    from ctypes import wintypes
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    advapi.InitializeAcl.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
    advapi.InitializeAcl.restype = wintypes.BOOL
    advapi.SetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD] + 4 * [ctypes.c_void_p]
    advapi.SetNamedSecurityInfoW.restype = wintypes.DWORD
    # An empty list. Never pass no list at all: that would give everyone full access.
    empty = ctypes.create_string_buffer(8)
    if not advapi.InitializeAcl(empty, len(empty), 2):  # ACL_REVISION
        raise ctypes.WinError(ctypes.get_last_error())
    file_object, dacl, unprotected = 1, 0x00000004, 0x20000000
    code = advapi.SetNamedSecurityInfoW(os.path.abspath(path), file_object, dacl | unprotected,
                                        None, None, empty, None)
    if code:
        raise ctypes.WinError(code)


def _restore_permissions(paths):
    """The names of the files that kept the private permissions."""
    failed = []
    if os.name == 'nt':
        for path in paths:
            try:
                inherit_permissions(path)
            except OSError:  # the output is complete, so report this and do not fail the run
                failed.append(path.name)
    return failed


def move_no_clobber(source, target):
    """Move source to target. Fail with FileExistsError if target exists."""
    for delay in _RETRY_DELAYS:
        try:
            return _move_once(source, target)
        except PermissionError:
            time.sleep(delay)
    return _move_once(source, target)


def remove_staging(folder):
    """Delete a staging folder. Wait and try again while another program holds one of its files."""
    for delay in _RETRY_DELAYS:
        shutil.rmtree(folder, ignore_errors=True)
        if not os.path.exists(folder):
            return
        time.sleep(delay)
    shutil.rmtree(folder, ignore_errors=True)


def _move_once(source, target):
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
    """Publish both files. Return the names of files whose permissions could not be restored."""
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
    return _restore_permissions([report, dest])
