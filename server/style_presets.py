"""Shared model-style presets used by project setup and generation jobs."""

STYLE_PRESETS = {
    "realistic": {
        "id": "realistic", "label": "写实",
        "description": "自然体积与真实结构，保留细腻面部、发丝和服装褶皱。",
        "featurePrompt": "写实三维角色；自然人体比例与头部体积；清晰的眼窝、鼻梁、嘴唇和下颌结构；真实发束与服装褶皱；连续曲面和可信厚度。",
        "negativePrompt": "避免扁平纸片、符号化五官、过度夸张比例和低浮雕结构。",
        "viewWeights": {"front": 1.8, "side": 1.0, "back": 0.7}, "depthScale": 1.0, "featureRelief": 1.0,
    },
    "cartoon": {
        "id": "cartoon", "label": "卡通",
        "description": "圆润轮廓与适度夸张，减少写实解剖和表面噪声。",
        "featurePrompt": "卡通化三维角色；圆润清晰的大块轮廓；简化人体解剖；头发块面化；弱化眼窝、鼻梁和嘴唇；服装褶皱概括为少量特征形。",
        "negativePrompt": "避免毛孔、写实发丝、尖锐骨骼结构、密集微小褶皱和扫描噪声。",
        "viewWeights": {"front": 1.4, "side": 1.6, "back": 0.9}, "depthScale": 0.82, "featureRelief": 0.72,
    },
    "chibi": {
        "id": "chibi", "label": "Q版",
        "description": "大头小身、扁平毛绒感，五官和服饰细节以特征形表达。",
        "featurePrompt": "Q版扁平毛绒玩具角色；大头小身；前后厚度较薄；脸部像柔软布面；额头、鼻口和下巴接近垂直轮廓；鼻口仅作轻微浅浮雕；眼睛、头发、辫子和服饰纹样用清晰的大块特征形表达。",
        "negativePrompt": "避免球形写实头骨、深眼窝、突出鼻梁和嘴唇、真实发丝、复杂皮肤结构、尖锐褶皱和写实雕塑感。",
        "viewWeights": {"front": 1.2, "side": 2.2, "back": 1.0}, "depthScale": 0.62, "featureRelief": 0.45,
    },
}

DEFAULT_STYLE = "realistic"

def style_preset(style_id: str | None) -> dict:
    return STYLE_PRESETS.get(style_id or DEFAULT_STYLE, STYLE_PRESETS[DEFAULT_STYLE]).copy()

def public_style_presets() -> list[dict]:
    return [preset.copy() for preset in STYLE_PRESETS.values()]
