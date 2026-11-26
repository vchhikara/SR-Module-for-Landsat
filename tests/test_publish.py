"""Publication on its own. No GDAL, so the Windows CI job runs these too."""
import os
import subprocess

import pytest

from landsat_sr import publish


def access_list(path):
    """The access entries that icacls prints for one file, without the path."""
    done = subprocess.run(['icacls', path.name], cwd=str(path.parent), capture_output=True, text=True,
                          check=True)
    lines = done.stdout.replace(path.name, '', 1).splitlines()
    return sorted(line.strip() for line in lines if ':(' in line)


def published_pair(folder):
    staging = folder / '.qgis_sr_test'
    os.mkdir(staging, 0o700)  # the same mode as the engine
    (staging / 'result.tif').write_bytes(b'tif')
    (staging / 'report.json').write_bytes(b'{}')
    dest = folder / 'out.tif'
    warnings = publish.publish_pair(staging / 'result.tif', staging / 'report.json', dest)
    return dest, publish.report_path(dest), warnings


def test_publication_moves_both_files(tmp_path):
    dest, report, warnings = published_pair(tmp_path)
    assert dest.read_bytes() == b'tif' and report.read_bytes() == b'{}'
    assert warnings == []


@pytest.mark.skipif(os.name != 'nt', reason='Windows access lists')
def test_published_files_get_the_permissions_of_the_output_folder(tmp_path):
    folder = tmp_path / 'shared'
    folder.mkdir()
    # An entry that new files inherit: S-1-1-0 is the "Everyone" group, here with read access.
    subprocess.run(['icacls', str(folder), '/grant', '*S-1-1-0:(OI)(CI)R'], check=True, capture_output=True)
    control = folder / 'normal_file.txt'
    control.write_bytes(b'x')
    expected = access_list(control)
    dest, report, _ = published_pair(folder)
    assert access_list(dest) == expected
    assert access_list(report) == expected


@pytest.mark.skipif(os.name != 'nt', reason='Windows access lists')
def test_a_permission_failure_keeps_the_output_and_is_reported(tmp_path, monkeypatch):
    def refuse(path):
        raise OSError(1, 'not supported on this volume')
    monkeypatch.setattr(publish, 'inherit_permissions', refuse)
    dest, report, warnings = published_pair(tmp_path)
    assert dest.is_file() and report.is_file()
    assert warnings == ['out.tif.json', 'out.tif']
