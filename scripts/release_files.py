# SPDX-License-Identifier: GPL-3.0-or-later
"""The one list of files that a release may contain, and the checks that all builders share."""
import os
from pathlib import Path
import stat

PLUGIN_FOLDER = 'landsat_sr'
RELEASE_FILES = (
    'CHANGELOG.md', 'LICENSE', 'README.md', 'THIRD_PARTY_NOTICES.md', '__init__.py', 'constants.py',
    'engine.py', 'icon.png', 'metadata.txt', 'plugin.py', 'publish.py', 'raster.py', 'redact.py',
    'runtime_config.py', 'stream_worker.py', 'tiling.py', 'weights/MODEL_SHA256.txt', 'worker_client.py',
)
CACHE_NAMES = ('__pycache__', '.pytest_cache', '.ruff_cache', '.mypy_cache')
BINARY_SUFFIXES = ('.onnx', '.exe', '.dll', '.so', '.pyd', '.dylib', '.bin', '.pth', '.pt', '.zip',
                   '.whl', '.pyc', '.pyo')
# PE, ELF, Mach-O (both byte orders and fat), ZIP and compiled-library archives.
BINARY_MAGIC = (b'MZ', b'\x7fELF', b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf', b'\xce\xfa\xed\xfe',
                b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'PK\x03\x04', b'!<arch>')


def looks_binary(name, head):
    return name.casefold().endswith(BINARY_SUFFIXES) or head.startswith(BINARY_MAGIC)


def is_link(path):
    """True for symbolic links and for Windows junctions and other reparse points."""
    info = os.lstat(path)
    reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & reparse)


def refuse_links(root):
    """Raise if the tree contains any link. A builder must never follow one out of the tree."""
    root = Path(root)
    if is_link(root):
        raise ValueError('The folder is a link: {}'.format(root.name))
    for folder, folders, names in os.walk(root, followlinks=False):
        for name in folders + names:
            path = os.path.join(folder, name)
            if is_link(path):
                raise ValueError('Links are not allowed in a package: {}'.format(
                    Path(path).relative_to(root).as_posix()))
