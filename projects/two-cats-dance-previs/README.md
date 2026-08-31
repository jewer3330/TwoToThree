# 双猫舞蹈本地预演测试

目标：验证“项目总控 → 分镜 → 关键帧 → ComfyUI 批量生成 → 质检 → 剪辑”的最小闭环。

本轮只使用本地 Wan 2.2 TI2V 5B，不消耗云端额度。预演以动作可读性和镜头衔接为主，不作为最终成片质量标准。

## v2 多机位测试准备

第二轮已拆成 3 个动作组、每组 3 个固定机位。详见：

- `multicam-plan.md`：机位设计、时间线、止损点和云端升级规则。
- `multicam-prompts.json`：9 个镜头的机位、动作、seed 与关键帧状态。
- `batch/multicam-tasks.csv`：ComfyUI 批量任务队列和最终生成状态。
- `qa/multicam-criteria.md`：单镜头和跨机位的通过标准。
- `qa/multicam-report-v2.md`：本轮逐镜结果、重试与正式版升级建议。
- `exports/two-cats-multicam-previs-v2.mp4`：99 帧多机位测试剪辑。
- `edit-v3.md`：动作匹配切点和短溶解的剪辑决策表。
- `exports/two-cats-multicam-previs-v3-smooth.mp4`：自然切换优化版。

## 舞蹈参考

- `reference/pulp-fiction-60s/reference-first-60s.mp4`：用户提供参考视频的前 60 秒项目代理。
- `reference/pulp-fiction-60s/reference-analysis.md`：动作、镜头切点和双猫改编规则。
- `reference/pulp-fiction-60s/adaptation-plan.json`：下一轮 8 秒动作/机位测试计划。
- `reference/pulp-fiction-60s/headswap-test/`：参考视频三种景别的双猫换头静帧测试。
- `reference/pulp-fiction-60s/headswap-video-test/`：本地 ComfyUI 三秒整体镜头还原与并排对照。

## 固定角色设定

- 黑猫：黑色短毛猫脸，白色长袖衬衫，黑色高腰长裤。
- 橘猫：橘色短毛猫脸，黑色西装、白衬衫和黑领带。
- 两只猫保持拟人直立比例；毛色、脸型、服装和体型在所有镜头中不改变。
- 复古餐厅、暖色钨丝灯、青绿色幕布、黑白棋盘地面。

## 技术基线

- 模型：Wan 2.2 TI2V 5B FP16
- 分辨率：640×352
- 每镜头：33帧，24 FPS，约1.375秒
- 采样：12步，CFG 5，去噪1.0
- 生成后逐帧抽样质检，再拼接成预演样片。
