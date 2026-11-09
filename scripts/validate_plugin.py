"""Dependency-free structural verification for QGIS Python plugin packages."""

import argparse
import ast
import configparser
from pathlib import Path
import re
import struct
import sys
import zipfile

PLUGIN_FOLDER = 'landsat_sr'
MANDATORY = ('__init__.py', 'metadata.txt', 'LICENSE', 'icon.png')
METADATA_REQUIRED = (
    'name', 'qgisMinimumVersion', 'description', 'about', 'version',
    'author', 'email', 'repository',
)


def validate_tree(plugin, reject_cache=False):
    """Return explicit failures, without importing QGIS or using third parties."""
    plugin = Path(plugin)
    errors = []
    if not plugin.is_dir() or plugin.name != PLUGIN_FOLDER:
        return ['Expected plugin root directory: {}'.format(PLUGIN_FOLDER)]
    for name in MANDATORY:
        if not (plugin / name).is_file():
            errors.append('Missing {}'.format(name))
    for file in plugin.rglob('*'):
        rel = file.relative_to(plugin)
        if file.is_symlink():
            errors.append('Symlink in package: {}'.format(rel))
        is_cache = any(part in ('.git', '__pycache__', '.pytest_cache') for part in rel.parts)
        if is_cache or file.suffix in ('.pyc', '.pyo'):
            if reject_cache:
                errors.append('Build/development cache: {}'.format(rel))
            continue
        if file.is_file() and file.suffix == '.py':
            try:
                ast.parse(file.read_text(encoding='utf-8'), filename=str(file))
            except (SyntaxError, UnicodeError) as exc:
                errors.append('Python invalid {}: {}'.format(rel, exc))
    if (plugin / '__init__.py').is_file():
        try:
            mod = ast.parse((plugin / '__init__.py').read_text(encoding='utf-8'))
            if 'classFactory' not in [n.name for n in mod.body if isinstance(n, ast.FunctionDef)]:
                errors.append('__init__.py lacks classFactory')
        except (SyntaxError, UnicodeError):
            pass
    metadata_path = plugin / 'metadata.txt'
    if metadata_path.is_file():
        config = configparser.ConfigParser(interpolation=None)
        try:
            config.read_string(metadata_path.read_text(encoding='utf-8-sig'))
            if not config.has_section('general'):
                errors.append('Missing [general] metadata section')
            else:
                data = config['general']
                for field in METADATA_REQUIRED:
                    if not data.get(field, '').strip():
                        errors.append('Missing required metadata key: {}'.format(field))
                if not re.fullmatch(r'\d+(?:\.\d+){1,3}', data.get('version', '')):
                    errors.append('Invalid metadata version')
                if not re.fullmatch(r'\d+(?:\.\d+){1,3}', data.get('qgisMinimumVersion', '')):
                    errors.append('Invalid minimum QGIS version')
                if not re.fullmatch(r'\d+(?:\.\d+){1,3}', data.get('qgisMaximumVersion', '')):
                    errors.append('Missing or invalid qgisMaximumVersion')
                for field in ('tracker', 'homepage'):
                    if not data.get(field, '').startswith('https://'):
                        errors.append('Missing {} URL'.format(field))
                if data.get('category') not in ('Vector', 'Raster', 'Database', 'Web', 'Mesh'):
                    errors.append('Invalid plugin category')
                for field in ('experimental', 'deprecated'):
                    if data.get(field, '').lower() not in ('true', 'false'):
                        errors.append('Invalid {} value'.format(field))
                icon = data.get('icon', '')
                if icon:
                    icon_path = Path(icon)
                    if icon_path.is_absolute() or '..' in icon_path.parts:
                        errors.append('Icon path escapes plugin root')
                    elif not (plugin / icon_path).is_file():
                        errors.append('Missing metadata icon')
        except (configparser.Error, UnicodeError) as exc:
            errors.append('Invalid metadata: {}'.format(exc))
    icon = plugin / 'icon.png'
    if icon.is_file():
        with icon.open('rb') as stream:
            header = stream.read(24)
        if len(header) < 24 or header[:8] != b'\x89PNG\r\n\x1a\n':
            errors.append('Icon is not a valid PNG header')
        else:
            width, height = struct.unpack('>II', header[16:24])
            if not width or not height:
                errors.append('Invalid PNG dimensions')
    for banned in ('.onnx', '.exe', '.dll', '.so', '.pyd'):
        for file in plugin.rglob('*' + banned):
            errors.append('Binary file not allowed on the QGIS site: {}'.format(file.relative_to(plugin)))
    return errors


def validate_zip(path):
    errors = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if not names:
            errors.append('Empty ZIP')
        for member in archive.infolist():
            name = member.filename
            components = Path(name).parts
            if (not components or components[0] != PLUGIN_FOLDER
                    or name.startswith('/') or '..' in components):
                errors.append('Unsafe/unexpected ZIP location: {}'.format(name))
            if member.flag_bits & 0x1:
                errors.append('Encrypted ZIP member: {}'.format(name))
            if any(part in ('.git', '__pycache__', '.pytest_cache') for part in components) or name.endswith(('.pyc', '.pyo')):
                errors.append('Cache or compiled file in ZIP: {}'.format(name))
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                errors.append('Symbolic link in ZIP: {}'.format(name))
        if len(names) != len(set(names)):
            errors.append('Duplicate ZIP names')
        for item in MANDATORY:
            if PLUGIN_FOLDER + '/' + item not in names:
                errors.append('Missing packaged {}'.format(item))
        total = sum(m.file_size for m in archive.infolist())
        if total > 25 * 1024 * 1024:
            errors.append('Package exceeds 25 MB')
        for name in names:
            if name.endswith(('.onnx', '.exe', '.dll', '.so', '.pyd')):
                errors.append('Binary file in ZIP: {}'.format(name))
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
