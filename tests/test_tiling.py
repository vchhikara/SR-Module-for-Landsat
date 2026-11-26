"""M-04: one global grid. The result must not depend on how the raster is split."""
import numpy as np
import pytest

from landsat_sr import tiling

SIZES = [1, 2, 63, 64, 65, 111, 112, 113, 191, 192, 193, 223, 224, 225, 255, 256, 257, 577]


@pytest.mark.parametrize('length', SIZES)
def test_weights_sum_to_one_everywhere(length):
    positions, weights = tiling.axis_weights(length)
    total = np.zeros(length * 4)
    for position, weight in zip(positions, weights):
        assert (weight > 0).all()
        total[position * 4:position * 4 + len(weight)] += weight
    np.testing.assert_allclose(total, 1.0, atol=1e-6)


@pytest.mark.parametrize('length', SIZES)
def test_grid_covers_the_axis(length):
    positions = tiling.starts(length)
    covered = np.zeros(length, bool)
    for position in positions:
        covered[position:position + 64] = True
    assert covered.all()
    assert positions == sorted(set(positions))
