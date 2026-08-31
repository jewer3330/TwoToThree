import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Box,
  CheckCircle2,
  Cpu,
  FileBox,
  Image,
  Layers3,
  Play,
  Settings2,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { Button, PageHeader } from "../App";
const flow = [
  ["主体分析", Cpu],
  ["Hunyuan3D", Box],
  ["GLB 检查", CheckCircle2],
  ["四视图渲染", Image],
  ["材质处理", Layers3],
  ["网页优化", FileBox],
] as const;
const viewLabels: Record<string, string> = {
  front: "正面",
  side: "侧面",
  back: "背面",
};
function ViewWeightSlider({
  role,
  value,
  onChange,
}: {
  role: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="view-weight">
      <span>
        {viewLabels[role]}权重 <b>{value.toFixed(1)}</b>
      </span>
      <input
        type="range"
        min="0.1"
        max="3"
        step="0.1"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <small>0.1</small>
      <small>3.0</small>
    </label>
  );
}
export default function PlanPage() {
  const { projectId = "" } = useParams(),
    nav = useNavigate();
  const [plan, setPlan] = useState<any>();
  const [consumption, setConsumption] = useState<any>();
  const [error, setError] = useState("");
  useEffect(() => {
    api
      .plan(projectId)
      .then(async (value: any) => {
        const referenceSetId = new URLSearchParams(location.search).get(
          "referenceSetId",
        );
        const next = { ...value, referenceSetId: referenceSetId || undefined };
        setPlan(next);
        if (referenceSetId)
          setConsumption(await api.referenceConsumption(referenceSetId));
      })
      .catch((e) => setError(e.message));
  }, [projectId]);
  const setQuality = (geometryQuality: string) =>
    setPlan({
      ...plan,
      geometryQuality,
      textureResolution:
        geometryQuality === "standard"
          ? 0
          : geometryQuality === "high"
            ? 2048
            : 4096,
      faceRefinement: geometryQuality === "ultra",
    });
  const start = async () => {
    try {
      await api.updatePlan(projectId, plan);
      const job = await api.createJob(projectId);
      nav(`/jobs/${job.id}`);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  if (!plan)
    return (
      <div className="loading">
        <span />
        正在生成转换方案…
      </div>
    );
  return (
    <>
      <PageHeader
        eyebrow="步骤 3 / 3 · 方案确认"
        title="转换方案确认"
        description="质量等级同时锁定几何、纹理和脸部精修能力。"
      />
      <div className="plan-layout">
        <section>
          <div className="panel pipeline">
            <div className="section-title">
              <h2>所选转换流程</h2>
              <span>推荐路线</span>
            </div>
            <div className="pipeline-flow">
              {flow.map(([label, I], i) => (
                <div className="flow-step" key={label}>
                  <em>{i + 1}</em>
                  <I />
                  <b>{label}</b>
                </div>
              ))}
            </div>
            <div className="fallback">
              <span>质量路线</span>
              <b>标准 256 / 无纹理</b> → <b>高 384 / 2K</b> →{" "}
              <b>超高 512 / 脸部精修 / 4K</b>
            </div>
          </div>
          <div className="metric-cards">
            <div>
              <Cpu />
              <small>主生成后端</small>
              <b>Hunyuan3D</b>
            </div>
            <div>
              <Box />
              <small>几何分辨率</small>
              <b>
                {
                  { standard: 256, high: 384, ultra: 512 }[
                    plan.geometryQuality as "standard" | "high" | "ultra"
                  ]
                }
              </b>
            </div>
            <div>
              <Image />
              <small>纹理分辨率</small>
              <b>
                {plan.textureResolution
                  ? `${plan.textureResolution}²`
                  : "无纹理"}
              </b>
            </div>
            <div>
              <Layers3 />
              <small>脸部精修</small>
              <b>{plan.faceRefinement ? "启用" : "关闭"}</b>
            </div>
          </div>
          <div className="panel outputs">
            <h2>交付内容</h2>
            {[
              "可验收 GLB",
              "正面 / 左 3/4 / 侧面 / 背面渲染",
              "模型统计与质量报告",
              "配置快照与阶段日志",
            ].map((x) => (
              <span key={x}>
                <CheckCircle2 />
                {x}
              </span>
            ))}
          </div>
          {consumption && (
            <div className="panel outputs">
              <h2>Reference Set 实际消费映射</h2>
              {Object.entries(consumption.hunyuanInputs).map(
                ([role, item]: any) => (
                  <span key={role}>
                    <CheckCircle2 />
                    {role} → Hunyuan3D-2mv · {item.name} ·{" "}
                    {item.sha256.slice(0, 12)}
                  </span>
                ),
              )}
              {consumption.blenderOnlyAssets.map((item: any) => (
                <span key={`${item.assetId}-${item.purpose}`}>
                  <Layers3 />
                  {item.viewRole} → 仅 Blender/{item.purpose} · {item.name}
                </span>
              ))}
              {consumption.warnings.map((warning: string) => (
                <div className="notice danger" key={warning}>
                  {warning}
                </div>
              ))}
            </div>
          )}
        </section>
        <aside>
          <div className="panel risk-panel">
            <h2>
              <AlertTriangle /> 已知限制与近似
            </h2>
            {plan.limitations.map((x: string) => (
              <p key={x}>• {x}</p>
            ))}
          </div>
          <div className="panel settings-panel">
            <h2>
              <Settings2 /> 质量等级
            </h2>
            <label>
              主后端
              <select
                value={plan.primaryBackend}
                onChange={(e) =>
                  setPlan({ ...plan, primaryBackend: e.target.value })
                }
              >
                <option value="hunyuan3d">Hunyuan3D</option>
                <option value="sf3d">Stable Fast 3D</option>
                <option value="triposr">TripoSR</option>
              </select>
            </label>
            <label>
              质量路线
              <select
                value={plan.geometryQuality}
                onChange={(e) => setQuality(e.target.value)}
              >
                <option value="standard">标准：256 几何，无纹理</option>
                <option value="high">高：384 几何＋2048 纹理</option>
                <option value="ultra">
                  超高：512 几何＋脸部精修＋4096 纹理
                </option>
              </select>
            </label>
            <label>
              纹理策略
              <input
                value={
                  plan.textureResolution
                    ? `三视图投射 · ${plan.textureResolution}×${plan.textureResolution}`
                    : "关闭"
                }
                disabled
              />
            </label>
            <div className="style-prompt-preview">
              <b>模型风格 · {plan.stylePreset?.label || plan.modelStyle}</b>
              <p>{plan.stylePreset?.featurePrompt}</p>
              <small>反向约束：{plan.stylePreset?.negativePrompt}</small>
            </div>
            <label>
              三视图视觉增强
              <select
                value={plan.visualConditioning?.mode || "auto"}
                onChange={(e) =>
                  setPlan({
                    ...plan,
                    visualConditioning: {
                      ...plan.visualConditioning,
                      enabled: e.target.value !== "original",
                      mode: e.target.value,
                    },
                  })
                }
              >
                <option value="auto">
                  自动：写实保留原图，卡通/Q版强化轮廓
                </option>
                <option value="original">关闭：使用规范化原图</option>
                <option value="contour">轮廓强化 RGB（推荐）</option>
                <option value="rgb_depth">RGB＋弱深度明暗（实验）</option>
              </select>
            </label>
            {plan.visualConditioning?.mode === "rgb_depth" && (
              <label>
                深度明暗混合{" "}
                <b>
                  {Math.round(
                    (plan.visualConditioning?.depthBlend ?? 0.15) * 100,
                  )}
                  %
                </b>
                <input
                  type="range"
                  min="0.05"
                  max="0.25"
                  step="0.05"
                  value={plan.visualConditioning?.depthBlend ?? 0.15}
                  onChange={(e) =>
                    setPlan({
                      ...plan,
                      visualConditioning: {
                        ...plan.visualConditioning,
                        depthBlend: Number(e.target.value),
                      },
                    })
                  }
                />
                <small>纯深度图只保存为实验产物，不直接送入 Hunyuan。</small>
              </label>
            )}
            <div className="view-weight-group">
              <h3>三视图权重</h3>
              <p>提高正面权重可增强脸部条件，过高可能削弱侧面和背面轮廓。</p>
              {(["front", "side", "back"] as const).map((role) => (
                <ViewWeightSlider
                  key={role}
                  role={role}
                  value={
                    plan.viewWeights?.[role] ??
                    { front: 1.8, side: 1, back: 0.7 }[role]
                  }
                  onChange={(value) =>
                    setPlan({
                      ...plan,
                      viewWeights: { ...plan.viewWeights, [role]: value },
                    })
                  }
                />
              ))}
            </div>
            <label className="check">
              <input
                type="checkbox"
                checked={plan.segmentationRequired}
                onChange={(e) =>
                  setPlan({ ...plan, segmentationRequired: e.target.checked })
                }
              />{" "}
              要求分件
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={plan.rigRequired}
                onChange={(e) =>
                  setPlan({ ...plan, rigRequired: e.target.checked })
                }
              />{" "}
              需要骨骼
            </label>
          </div>
        </aside>
      </div>
      {error && <div className="notice danger">{error}</div>}
      <div className="sticky-actions">
        <Button
          kind="secondary"
          onClick={() => nav(`/validation/${projectId}`)}
        >
          返回修改
        </Button>
        <span>配置确认后不可原地修改</span>
        <Button onClick={start}>
          <Play /> 确认并开始转换
        </Button>
      </div>
    </>
  );
}
