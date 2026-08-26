import { useEffect, useState } from "react";
import { Check, LockKeyhole, WandSparkles } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import type { Version } from "../types";
import { Button, PageHeader } from "../App";
const defaults = [
  "geometryRepair",
  "uvUnwrap",
  "pbrMaterials",
  "webOptimization",
  "visualReview",
];
export default function RefinementConfigPage() {
  const { versionId = "" } = useParams(),
    nav = useNavigate();
  const [version, setVersion] = useState<Version>(),
    [modules, setModules] = useState<Record<string, any>>({}),
    [selected, setSelected] = useState(defaults),
    [instructions, setInstructions] = useState(""),
    [strength, setStrength] = useState("conservative"),
    [uv, setUv] = useState("preserve_or_smart"),
    [texture, setTexture] = useState(2048),
    [template, setTemplate] = useState("neutral"),
    [minTriangles, setMin] = useState(20000),
    [maxTriangles, setMax] = useState(120000),
    [maxMB, setMaxMB] = useState(20),
    [preserveThickness, setPreserveThickness] = useState(true),
    [maxThicknessLoss, setMaxThicknessLoss] = useState(8),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    Promise.all([api.version(versionId), api.refinementModules()])
      .then(([v, m]) => {
        setVersion(v);
        setModules(m);
      })
      .catch((e) => setError(e.message));
  }, [versionId]);
  const toggle = (id: string) =>
    setSelected((x) =>
      x.includes(id) ? x.filter((v) => v !== id) : [...x, id],
    );
  const create = async () => {
    setBusy(true);
    setError("");
    try {
      const job = await api.createRefinement({
        sourceVersionId: versionId,
        modules: selected,
        instructions,
        geometryRepairStrength: strength,
        uvStrategy: uv,
        uvIslandMargin: 0.03,
        materialTemplate: template,
        targetTriangleRange: [minTriangles, maxTriangles],
        textureResolution: texture,
        maxWebGlbMB: maxMB,
        preserveThickness,
        maxThicknessLoss: maxThicknessLoss / 100,
        maxDecimationPerPass: 0.2,
        minThinAxisRatio: 0.08,
      });
      nav(`/refinement/jobs/${job.id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  if (!version)
    return (
      <div className="loading">
        <span />
        正在读取基线版本…
      </div>
    );
  return (
    <>
      <PageHeader
        eyebrow={`源版本 v${String(version.number).padStart(3, "0")}`}
        title="创建 Blender 自动精修"
        description="源版本必须已验收锁定；任务将派生新版本，绝不覆盖基线。"
      />
      <div className="refine-config">
        <section>
          <div className="panel source-card">
            <LockKeyhole />
            <div>
              <small>已锁定源版本</small>
              <h2>v{String(version.number).padStart(3, "0")}</h2>
              <p>
                {version.model?.label} ·{" "}
                {version.model
                  ? `${(version.model.byteSize / 1048576).toFixed(2)} MB`
                  : "无模型"}
              </p>
            </div>
          </div>
          <h2 className="section-heading">自动精修模块</h2>
          <div className="module-grid">
            {Object.entries(modules).map(([id, m]) => (
              <button
                key={id}
                className={`module-card ${selected.includes(id) ? "selected" : ""}`}
                onClick={() => toggle(id)}
              >
                <i>{selected.includes(id) && <Check />}</i>
                <WandSparkles />
                <h3>{m.label}</h3>
                <em className={`cap-${m.capability}`}>
                  {m.capability === "automatic"
                    ? "自动执行"
                    : m.capability === "inferred"
                      ? "自动推断、待验收"
                      : m.capability === "manual"
                        ? "人工"
                        : "未配置"}
                </em>
                <p>{m.description}</p>
              </button>
            ))}
          </div>
        </section>
        <aside className="panel refine-summary">
          <h2>精修配置</h2>
          <label>
            几何修复强度
            <select
              value={strength}
              onChange={(e) => setStrength(e.target.value)}
            >
              <option value="conservative">保守</option>
              <option value="standard">标准</option>
            </select>
          </label>
          <label>
            UV 策略
            <select value={uv} onChange={(e) => setUv(e.target.value)}>
              <option value="preserve_or_smart">
                保留有效 UV，否则自动展开
              </option>
              <option value="smart">强制 Smart UV</option>
            </select>
          </label>
          <label>
            材质模板
            <select
              value={template}
              onChange={(e) => setTemplate(e.target.value)}
            >
              <option value="neutral">中性非金属</option>
              <option value="matte">哑光</option>
            </select>
          </label>
          <label>
            贴图分辨率
            <select
              value={texture}
              onChange={(e) => setTexture(Number(e.target.value))}
            >
              <option>1024</option>
              <option>2048</option>
              <option>4096</option>
            </select>
          </label>
          <label>
            最小三角面
            <input
              type="number"
              value={minTriangles}
              onChange={(e) => setMin(Number(e.target.value))}
            />
          </label>
          <label>
            最大三角面
            <input
              type="number"
              value={maxTriangles}
              onChange={(e) => setMax(Number(e.target.value))}
            />
          </label>
          <label>
            <span>
              <input
                type="checkbox"
                checked={preserveThickness}
                onChange={(e) => setPreserveThickness(e.target.checked)}
              />{" "}
              保护模型厚度（推荐）
            </span>
          </label>
          <label>
            最大允许厚度损失（%）
            <input
              type="number"
              min="1"
              max="30"
              disabled={!preserveThickness}
              value={maxThicknessLoss}
              onChange={(e) => setMaxThicknessLoss(Number(e.target.value))}
            />
          </label>
          <label>
            最大 GLB（MB）
            <input
              type="number"
              value={maxMB}
              onChange={(e) => setMaxMB(Number(e.target.value))}
            />
          </label>
          <label>
            重点说明
            <textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
            />
          </label>
          {error && <div className="notice danger">{error}</div>}
          <Button
            disabled={busy || !selected.length || minTriangles > maxTriangles}
            onClick={create}
          >
            {busy ? "创建中…" : "启动真实 Blender 精修"}
          </Button>
        </aside>
      </div>
    </>
  );
}
