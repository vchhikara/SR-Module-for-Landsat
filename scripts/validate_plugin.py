# SPDX-License-Identifier: GPL-3.0-or-later
"""Dependency-free verification of the QGIS plugin source tree and the repository ZIP."""

import argparse
import ast
import configparser
from pathlib import Path
import re
import stat
import struct
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_files import CACHE_NAMES, PLUGIN_FOLDER, RELEASE_FILES, is_link, looks_binary  # noqa: E402

MAX_BYTES = 25 * 1024 * 1024
METADATA_REQUIRED = (
    'name', 'qgisMinimumVersion', 'description', 'about', 'version',
    'author', 'email', 'repository',
)


def _validate_metadata(plugin, errors):
    config = configparser.ConfigParser(interpolation=None)
    try:
        config.read_string((plugin / 'metadata.txt').read_text(encoding='utf-8-sig'))
    except (configparser.Error, UnicodeError) as exc:
        errors.append('Invalid metadata: {}'.format(exc))
        return
    if not config.has_section('general'):
        errors.append('Missing [general] metadata section')
        return
    data = config['general']
    for field in METADATA_REQUIRED:
        if not data.get(field, '').strip():
            errors.append('Missing required metadata key: {}'.format(field))
    for field in ('version', 'qgisMinimumVersion', 'qgisMaximumVersion'):
        if not re.fullmatch(r'\d+(?:\.\d+){1,3}', data.get(field, '')):
            errors.append('Missing or invalid {}'.format(field))
    for field in ('tracker', 'homepage'):
        if not data.get(field, '').startswith('https://'):
            errors.append('Missing {} URL'.format(field))
    if data.get('category') not in ('Vector', 'Raster', 'Database', 'Web', 'Mesh'):
        errors.append('Invalid plugin category')
    for field in ('experimental', 'deprecated'):
        if data.get(field, '').lower() not in ('true', 'false'):
            errors.append('Invalid {} value'.format(field))
    icon = data.get('icon', '')
    if icon and icon not in RELEASE_FILES:
        errors.append('Metadata icon is not a release file')


def validate_tree(plugin):
    """Return explicit failures, without importing QGIS or using third parties."""
    plugin = Path(plugin)
    if not plugin.is_dir() or plugin.name != PLUGIN_FOLDER:
        return ['Expected plugin root directory: {}'.format(PLUGIN_FOLDER)]
    errors = []
    present = set()
    for path in sorted(plugin.rglob('*')):
        relative = path.relative_to(plugin)
        if is_link(path):
            errors.append('Link in package: {}'.format(relative.as_posix()))
            continue
        if any(part in CACHE_NAMES for part in relative.parts) or not path.is_file():
            continue
        name = relative.as_posix()
        present.add(name)
        if name not in RELEASE_FILES:
            errors.append('File is not in the release list: {}'.format(name))
        with path.open('rb') as stream:
            if looks_binary(name, stream.read(8)):
                errors.append('Binary file not allowed on the QGIS site: {}'.format(name))
        if path.suffix == '.py':
            try:
                ast.parse(path.read_text(encoding='utf-8'), filename=name)
            except (SyntaxError, UnicodeError) as exc:
                errors.append('Python invalid {}: {}'.format(name, exc))
    errors += ['Missing {}'.format(name) for name in RELEASE_FILES if name not in present]
    if '__init__.py' in present:
        try:
            module = ast.parse((plugin / '__init__.py').read_text(encoding='utf-8'))
            if 'classFactory' not in [n.name for n in module.body if isinstance(n, ast.FunctionDef)]:
                errors.append('__init__.py lacks classFactory')
        except (SyntaxError, UnicodeError):
            pass  # reported above
    if 'metadata.txt' in present:
        _validate_metadata(plugin, errors)
    if 'icon.png' in present:
        with (plugin / 'icon.png').open('rb') as stream:
            header = stream.read(24)
        if len(header) < 24 or header[:8] != b'\x89PNG\r\n\x1a\n':
            errors.append('Icon is not a valid PNG header')
        elif 0 in struct.unpack('>II', header[16:24]):
            errors.append('Invalid PNG dimensions')
    return errors


def validate_zip(path):
    """The ZIP must hold exactly the release files. Nothing is extracted to disk."""
    errors = []
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        names = [m.filename for m in members]
        expected = {PLUGIN_FOLDER + '/' + name for name in RELEASE_FILES}
        errors += ['Unexpected ZIP member: {}'.format(n) for n in sorted(set(names) - expected)]
        errors += ['Missing packaged {}'.format(n) for n in sorted(expected - set(names))]
        if len(names) != len({n.casefold() for n in names}):
            errors.append('Duplicate ZIP names')
        total = sum(m.file_size for m in members)
        if total > MAX_BYTES or Path(path).stat().st_size > MAX_BYTES:
            errors.append('Package exceeds 25 MB')
            return errors
        for member in members:
            if member.flag_bits & 0x1:
                errors.append('Encrypted ZIP member: {}'.format(member.filename))
                continue
            if stat.S_ISLNK(member.external_attr >> 16):
                errors.append('Symbolic link in ZIP: {}'.format(member.filename))
            with archive.open(member) as stream:
                if looks_binary(member.filename, stream.read(8)):
                    errors.append('Binary file in ZIP: {}'.format(member.filename))
        if not errors and archive.testzip() is not None:
            errors.append('Corrupted ZIP member')
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('plugin', help='Extracted plugin directory')
    parser.add_argument('--zip', help='Optional distribution ZIP for validation')
    args = parser.parse_args(argv)
    errors = validate_tree(args.plugin)
    if args.zip:
        errors.extend(validate_zip(args.zip))
    if errors:
        for message in errors:
            print('FAIL:', message)
        return 1
    print('PASS: plugin structure, metadata, Python syntax, icon, and package layout')
    return 0


if __name__ == '__main__':
    sys.exit(main())
