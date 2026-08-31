import { useCallback, useEffect, useState } from "react";
import {
  Box,
  Bookmark,
  Download,
  MessageSquarePlus,
  Paperclip,
  Send,
  Trash2,
  Wrench,
  XCircle,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import type { Version, VersionComment } from "../types";
import ModelViewport, {
  type AnnotationSnapshot,
} from "../components/ModelViewport";
import StlExportDialog from "../components/StlExportDialog";
import { PageHeader } from "../App";
const empty = {
  title: "",
  description: "",
  category: "geometry",
  severity: "normal",
  recommendedRoute: "reference_regeneration",
};
export default function ReviewPage() {
  const { projectId = "" } = useParams(),
    nav = useNavigate();
  const [versions, setVersions] = useState<Version[]>([]),
    [active, setActive] = useState<Version>(),
    [comments, setComments] = useState<VersionComment[]>([]),
    [selected, setSelected] = useState<string[]>([]),
    [current, setCurrent] = useState<VersionComment>(),
    [draft, setDraft] = useState<any>(empty),
    [anchor, setAnchor] = useState<AnnotationSnapshot>(),
    [reply, setReply] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState("");
  const [showStlExport, setShowStlExport] = useState(false);
  const load = useCallback(
    (vid: string) =>
      api
        .comments(vid)
        .then(setComments)
        .catch((e) => setError(e.message)),
    [],
  );
  const loadVersions = useCallback(async () => {
    const v = await api.versions(projectId);
    setVersions(v);
    return v;
  }, [projectId]);
  useEffect(() => {
    loadVersions()
      .then((v) => {
        setActive(v[0]);
        if (v[0]) load(v[0].id);
      })
      .catch((e) => setError(e.message));
  }, [load, loadVersions]);
  const choose = (v: Version) => {
    setActive(v);
    setCurrent(undefined);
    setSelected([]);
    void load(v.id);
  };
  const setBase = async (v: Version) => {
    if (v.isBase) return;
    if (
      !window.confirm(
        `将 v${String(v.number).padStart(3, "0")} 设为 Base 版本？后续修订默认以它为基础。`,
      )
    )
      return;
    setBusy(v.id);
    setError("");
    try {
      const changed = await api.setBaseVersion(v.id);
      setVersions((x) =>
        x.map((item) =>
          item.id === changed.id ? changed : { ...item, isBase: false },
        ),
      );
      setActive((x) => (x?.id === changed.id ? changed : x));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  const removeVersion = async (v: Version) => {
    if (
      !window.confirm(
        `确定删除 v${String(v.number).padStart(3, "0")}？其模型、Comment 和任务产物将一并删除，无法恢复。`,
      )
    )
      return;
    setBusy(v.id);
    setError("");
    try {
      await api.deleteVersion(v.id);
      const next = (await loadVersions()).find((x) => x.id !== v.id);
      setActive(next);
      setCurrent(undefined);
      setSelected([]);
      if (next) await load(next.id);
      else setComments([]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  const save = async () => {
    if (!active) return;
    try {
      const c = await api.createComment(active.id, { ...draft, ...anchor });
      setComments((x) => [c, ...x]);
      setDraft(empty);
      setAnchor(undefined);
      setCurrent(c);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const update = (c: VersionComment) => {
    setComments((x) => x.map((v) => (v.id === c.id ? c : v)));
    setCurrent(c);
  };
  if (!active)
    return (
      <div className="loading">
        <span />
        正在读取版本…
      </div>
    );
  return (
    <>
      <PageHeader
        eyebrow={`项目 ${projectId.slice(0, 8)} · 版本验收`}
        title="模型预览与 Comment 评审"
        description="一个 Comment 只描述一个问题；保存不会启动任务。双击模型可记录标注位置、相机视角和截图。"
      />
      <div className="comment-review-layout">
        <aside className="panel version-panel">
          <h2>版本历史</h2>
          {versions.map((v) => (
            <div
              className={
                active.id === v.id ? "version-row active" : "version-row"
              }
              key={v.id}
            >
              <button className="version-select" onClick={() => choose(v)}>
                <Box />
                <span>
                  <b>v{String(v.number).padStart(3, "0")}</b>
                  <small>{v.label}</small>
                </span>
                {v.isBase && <em>Base</em>}
              </button>
              <div className="version-actions">
                <button
                  title="设为 Base 版本"
                  aria-label={`设 v${v.number} 为 Base`}
                  disabled={busy === v.id || v.isBase}
                  onClick={() => void setBase(v)}
                >
                  <Bookmark />
                </button>
                <button
                  title="删除版本"
                  aria-label={`删除 v${v.number}`}
                  disabled={busy === v.id}
                  onClick={() => void removeVersion(v)}
                >
                  <Trash2 />
                </button>
              </div>
            </div>
          ))}
          <h2>筛选</h2>
          <p>
            当前版本 {comments.length} 条 · 已选 {selected.length} 条
          </p>
        </aside>
        <section className="review-center">
          {active.model ? (
            <ModelViewport
              url={active.model.url}
              onStats={() => {}}
              onSelect={() => {}}
              onAnnotate={setAnchor}
            />
          ) : (
            <div className="viewport-error">当前版本没有 GLB</div>
          )}
          <div className="download-bar">
            <button
              className="stl-export-trigger"
              onClick={() => setShowStlExport(true)}
            >
              <Download />
              Blender 导出 STL
            </button>
            <button onClick={() => setCurrent(undefined)}>
              <MessageSquarePlus />
              新建 Comment
            </button>
            <button
              disabled={!selected.length}
              onClick={() =>
                nav(
                  `/revisions/new/${active.id}?comments=${selected.join(",")}`,
                )
              }
            >
              <Wrench />
              创建修订任务（{selected.length}）
            </button>
          </div>
        </section>
        <aside className="panel comments-panel">
          <h2>Comments</h2>
          <div className="comment-list">
            {comments.map((c) => (
              <article
                className={current?.id === c.id ? "active" : ""}
                key={c.id}
                onClick={() => setCurrent(c)}
              >
                <input
                  type="checkbox"
                  checked={selected.includes(c.id)}
                  onChange={(e) => {
                    e.stopPropagation();
                    setSelected((x) =>
                      e.target.checked
                        ? [...x, c.id]
                        : x.filter((i) => i !== c.id),
                    );
                  }}
                />
                <b>
                  #{c.number} {c.title}
                </b>
                <small>
                  {c.severity} · {c.status}
                </small>
              </article>
            ))}
          </div>
          {current ? (
            <div className="comment-detail">
              <h3>
                #{current.number} {current.title}
              </h3>
              <p>{current.description}</p>
              <small>
                {current.category} · {current.recommendedRoute}
              </small>
              {current.screenshotUrl && <img src={current.screenshotUrl} />}
              <div className="reply-thread">
                {current.replies.map((r) => (
                  <p key={r.id}>
                    <b>{r.authorType}</b>
                    {r.body}
                  </p>
                ))}
              </div>
              <div className="inline-input">
                <input
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                  placeholder="回复…"
                />
                <button
                  onClick={async () => {
                    if (reply.trim()) {
                      update(await api.replyComment(current.id, reply));
                      setReply("");
                    }
                  }}
                >
                  <Send />
                </button>
              </div>
              <label className="attach">
                <Paperclip />
                上传辅助参考图
                <input
                  type="file"
                  accept="image/*"
                  onChange={async (e) => {
                    const f = e.target.files?.[0];
                    if (f)
                      update(await api.attachComment(current.id, "front", f));
                  }}
                />
              </label>
              <button
                onClick={async () =>
                  update(
                    current.status === "closed"
                      ? await api.reopenComment(current.id)
                      : await api.closeComment(current.id),
                  )
                }
              >
                <XCircle />
                {current.status === "closed" ? "重新打开" : "关闭 Comment"}
              </button>
            </div>
          ) : (
            <div className="comment-editor">
              <h3>新建独立 Comment</h3>
              {anchor && (
                <div className="notice success">
                  已记录 {anchor.meshName} 标注点与当前视角
                </div>
              )}
              <label>
                标题
                <input
                  value={draft.title}
                  onChange={(e) =>
                    setDraft({ ...draft, title: e.target.value })
                  }
                />
              </label>
              <label>
                详细说明
                <textarea
                  value={draft.description}
                  onChange={(e) =>
                    setDraft({ ...draft, description: e.target.value })
                  }
                />
              </label>
              <div className="field-pair">
                <label>
                  类型
                  <select
                    value={draft.category}
                    onChange={(e) =>
                      setDraft({ ...draft, category: e.target.value })
                    }
                  >
                    <option value="geometry">几何</option>
                    <option value="identity">身份特征</option>
                    <option value="intersection">穿插</option>
                    <option value="material">材质</option>
                    <option value="color">颜色</option>
                    <option value="other">其他</option>
                  </select>
                </label>
                <label>
                  严重程度
                  <select
                    value={draft.severity}
                    onChange={(e) =>
                      setDraft({ ...draft, severity: e.target.value })
                    }
                  >
                    <option value="blocking">阻断</option>
                    <option value="important">重要</option>
                    <option value="normal">一般</option>
                    <option value="note">备注</option>
                  </select>
                </label>
              </div>
              <label>
                处理路线
                <select
                  value={draft.recommendedRoute}
                  onChange={(e) =>
                    setDraft({ ...draft, recommendedRoute: e.target.value })
                  }
                >
                  <option value="reference_regeneration">参考图重生成</option>
                  <option value="blender_automatic">Blender 自动</option>
                  <option value="manual">人工处理</option>
                  <option value="not_configured">未配置</option>
                </select>
              </label>
              <button
                className="button"
                disabled={!draft.title.trim() || !draft.description.trim()}
                onClick={save}
              >
                保存 Comment
              </button>
            </div>
          )}
          {error && <div className="notice danger">{error}</div>}
        </aside>
      </div>
      {showStlExport && (
        <StlExportDialog
          versionId={active.id}
          versionNumber={active.number}
          onClose={() => setShowStlExport(false)}
        />
      )}
    </>
  );
}
