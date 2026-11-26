"""Build a local Windows test package from an existing trusted runtime and model.

This separate package is not suitable for upload to the QGIS plugin repository,
which does not accept bundled binaries. Review third-party redistribution rights
and notices before distributing it.
"""
import argparse
import hashlib
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from package_plugin import INCLUDE

EXPECTED_MODEL = '3f47670dfeba712d68cd479f11cfe25866453c08b840269102b7a037eebc8908'


def build(source, bundle, output):
    source, bundle, output = Path(source), Path(bundle), Path(output)
    model = bundle / 'weights' / 'real_hat_64.onnx'
    python = bundle / 'runtime' / 'python.exe'
    if not python.is_file() or not model.is_file():
        raise ValueError('Expected runtime/python.exe and weights/real_hat_64.onnx in the runtime bundle')
    digest = hashlib.sha256()
    with model.open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''): digest.update(block)
    if digest.hexdigest() != EXPECTED_MODEL:
        raise ValueError('Model SHA-256 does not match the expected model')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in INCLUDE:
            archive.write(source / name, 'landsat_sr/' + name)
        archive.write(model, 'landsat_sr/weights/real_hat_64.onnx')
        for path in sorted((bundle / 'runtime').rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix.lower() not in ('.pyc', '.pyo'):
                archive.write(path, 'landsat_sr/runtime/' + path.relative_to(bundle / 'runtime').as_posix())
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='landsat_sr')
    parser.add_argument('--bundle', required=True, help='Existing folder containing runtime/ and weights/')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(build(args.source, args.bundle, args.output))
