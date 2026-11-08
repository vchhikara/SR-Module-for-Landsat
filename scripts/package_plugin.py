"""Produce a reproducible ZIP containing exactly one QGIS plugin directory."""

import argparse
from pathlib import Path
import sys
import zipfile

from validate_plugin import validate_tree, validate_zip

PLUGIN_FOLDER = 'landsat_sr'
INCLUDE = (
    '__init__.py', 'plugin.py', 'stream_worker.py', 'onnx_worker.py',
    'metadata.txt', 'LICENSE', 'README.md', 'CHANGELOG.md', 'icon.png',
    'weights/MODEL_SHA256.txt',
)


def package_plugin(source, output):
    source, output = Path(source), Path(output)
    failures = validate_tree(source)
    if failures:
        raise ValueError('Source invalid: {}'.format('; '.join(failures)))
    missing = [name for name in INCLUDE if not (source / name).is_file()]
    if missing:
        raise ValueError('Missing runtime files: {}'.format(', '.join(missing)))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in sorted(INCLUDE):
            info = zipfile.ZipInfo(PLUGIN_FOLDER + '/' + name, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, (source / name).read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    errors = validate_zip(output)
    if errors:
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
