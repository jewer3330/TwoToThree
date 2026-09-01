from pathlib import Path


def test_render_defaults_to_preserving_source_materials():
    source=Path('pipeline/blender_render_job.py').read_text(encoding='utf-8')
    assert "choices=('preserve_source','calibrated_projection'),default='preserve_source'" in source
    assert "a.texture_mode=='calibrated_projection' and calibration_ok" in source
    assert "'sourceMaterialsPreserved':a.texture_mode=='preserve_source'" in source


def test_refiner_never_clears_existing_material_slots():
    source=Path('pipeline/blender_auto_refine.py').read_text(encoding='utf-8')
    assert 'o.data.materials.clear()' not in source
    assert "textureMode','preserve_source'" in source
    assert "请求参考图投射但缺少 projectionCalibration" in source
    assert "'referenceProjectionApplied':False" in source


def test_reference_image_is_not_connected_to_base_color_without_calibration():
    source=Path('pipeline/blender_auto_refine.py').read_text(encoding='utf-8')
    assert "base.image=images['base-color']" not in source
    assert '参考图只用于视觉验收' in source
