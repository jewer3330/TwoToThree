from PIL import Image,ImageDraw
from pipeline.multiview_visual_conditioning import build_candidates

def reference(width:int)->Image.Image:
    image=Image.new('RGBA',(128,128),(255,255,255,0));draw=ImageDraw.Draw(image);left=(128-width)//2;draw.rounded_rectangle((left,12,left+width,116),radius=18,fill=(90,140,210,255));return image

def test_candidates_preserve_silhouette_and_depth_is_not_selectable(tmp_path):
    images={'front':reference(78),'side':reference(42),'back':reference(76)}
    result=build_candidates(images,tmp_path,'rgb_depth','chibi',.15)
    assert result['report']['selectedMode']=='rgb_depth'
    assert result['report']['consistency']['passed']
    for role in images:
        record=result['report']['views'][role]
        assert record['candidates']['rgb_depth']['silhouettePreserved']
        assert record['candidates']['depthCue']['selectable'] is False
        assert result['images'][role].exists()

def test_auto_mode_keeps_realistic_and_contours_chibi(tmp_path):
    images={'front':reference(70),'side':reference(45),'back':reference(68)}
    assert build_candidates(images,tmp_path/'realistic','auto','realistic')['report']['selectedMode']=='original'
    assert build_candidates(images,tmp_path/'chibi','auto','chibi')['report']['selectedMode']=='contour'
