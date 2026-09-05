import pytest

from pipeline.blender_split_connected import normalization_plan


def test_normalization_centers_xy_grounds_z_and_scales_to_mm():
    plan = normalization_plan((-2.0, 4.0, -3.0), (4.0, 10.0, 1.0), 120)

    assert plan['scale'] == pytest.approx(30)
    assert plan['normalizedBounds']['min'] == pytest.approx((-90, -90, 0))
    assert plan['normalizedBounds']['max'] == pytest.approx((90, 90, 120))


@pytest.mark.parametrize('height', [9, 501])
def test_normalization_rejects_unsafe_target_height(height):
    with pytest.raises(ValueError):
        normalization_plan((0, 0, 0), (1, 1, 1), height)


def test_normalization_rejects_flat_z_bounds():
    with pytest.raises(ValueError):
        normalization_plan((0, 0, 2), (1, 1, 2), 120)
