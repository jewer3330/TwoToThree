import { Download, X } from "lucide-react";
import { useState } from "react";
import { api } from "../api";

interface Props {
  versionId: string;
  versionNumber: number;
  onClose: () => void;
}

export default function StlExportDialog({
  versionId,
  versionNumber,
  onClose,
}: Props) {
  const [filename, setFilename] = useState(
    `model-v${String(versionNumber).padStart(3, "0")}.stl`,
  );
  const [scope, setScope] = useState<"visible" | "all">("visible");
  const [unit, setUnit] = useState<"mm" | "cm" | "m">("mm");
  const [applyModifiers, setApplyModifiers] = useState(true);
  const [targetHeight, setTargetHeight] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api.exportStl(versionId, {
        filename,
        scope,
        unit,
        applyModifiers,
        targetHeightMm: targetHeight ? Number(targetHeight) : undefined,
      });
      const link = document.createElement("a");
      link.href = result.url;
      link.download = result.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      onClose();
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div
      className="export-dialog-backdrop"
      role="presentation"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <section
        className="export-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="stl-export-title"
      >
        <header>
          <div>
            <small>BLENDER 后台导出</small>
            <h2 id="stl-export-title">导出 STL</h2>
          </div>
          <button aria-label="关闭" onClick={onClose}>
            <X />
          </button>
        </header>
        <p>模型由服务器上的 Blender 打开并转换，网页预览不会参与几何导出。</p>
        <label>
          文件名
          <input
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
          />
        </label>
        <div className="field-pair">
          <label>
            导出范围
            <select
              value={scope}
              onChange={(e) => setScope(e.target.value as "visible" | "all")}
            >
              <option value="visible">可见网格</option>
              <option value="all">全部网格</option>
            </select>
          </label>
          <label>
            坐标换算
            <select
              value={unit}
              onChange={(e) => setUnit(e.target.value as "mm" | "cm" | "m")}
            >
              <option value="mm">米 → 毫米（×1000）</option>
              <option value="cm">米 → 厘米（×100）</option>
              <option value="m">保持米制数值（×1）</option>
            </select>
          </label>
        </div>
        <label>
          目标打印高度（mm）
          <input
            type="number"
            min="1"
            max="2000"
            step="1"
            value={targetHeight}
            placeholder="例如 120；留空保持当前比例"
            onChange={(e) => setTargetHeight(e.target.value)}
          />
          <small>Blender 会按所有导出网格的整体高度等比例缩放。</small>
        </label>
        <label className="export-check">
          <input
            type="checkbox"
            checked={applyModifiers}
            onChange={(e) => setApplyModifiers(e.target.checked)}
          />
          <span>
            <b>应用修改器</b>
            <small>导出细分、镜像、实体化等修改器的最终结果</small>
          </span>
        </label>
        <div className="notice">
          STL 不保存材质、贴图和单位。填写目标高度后，该高度优先于坐标换算设置。
        </div>
        {error && <div className="notice danger">{error}</div>}
        <footer>
          <button onClick={onClose}>取消</button>
          <button
            className="button"
            disabled={busy || !filename.trim() || (targetHeight !== "" && (Number(targetHeight) < 1 || Number(targetHeight) > 2000))}
            onClick={() => void submit()}
          >
            <Download />
            {busy ? "Blender 正在导出…" : "导出并下载"}
          </button>
        </footer>
      </section>
    </div>
  );
}
