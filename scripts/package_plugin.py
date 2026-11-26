# SPDX-License-Identifier: GPL-3.0-or-later
"""Produce a reproducible ZIP containing exactly one QGIS plugin directory."""

import argparse
from pathlib import Path
import shutil
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_files import PLUGIN_FOLDER, RELEASE_FILES, refuse_links  # noqa: E402
from validate_plugin import validate_tree, validate_zip  # noqa: E402


def add_member(archive, name, source):
    """Add a file with fixed metadata, so equal content gives equal ZIP bytes."""
    info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    if isinstance(source, bytes):
        archive.writestr(info, source, compresslevel=9)
        return
    info._compresslevel = 9  # type: ignore[attr-defined]  # ZipFile.open has no level argument
    info.file_size = Path(source).stat().st_size  # lets zipfile choose ZIP64
    with open(source, 'rb') as stream, archive.open(info, 'w') as out:
        shutil.copyfileobj(stream, out, 1024 * 1024)


def package_plugin(source, output):
    source, output = Path(source), Path(output)
    refuse_links(source)
    failures = validate_tree(source)
    if failures:
        raise ValueError('Source invalid: {}'.format('; '.join(failures)))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w') as archive:
        for name in sorted(RELEASE_FILES):
            add_member(archive, PLUGIN_FOLDER + '/' + name, (source / name).read_bytes())
    errors = validate_zip(output)
    if errors:
        output.unlink()
        raise ValueError('ZIP invalid: {}'.format('; '.join(errors)))
    return output


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default=PLUGIN_FOLDER)
    parser.add_argument('--output', default='dist/landsat_sr.zip')
    args = parser.parse_args(argv)
    print('PASS: packaged {}'.format(package_plugin(args.source, args.output)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
