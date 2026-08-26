import type {
  Project,
  Asset,
  Validation,
  Job,
  Version,
  RefinementJob,
  VersionComment,
  RevisionRequest,
  DetailPlan,
  DetailJob,
  StylePreset,
} from "./types";
const json = async <T>(r: Response): Promise<T> => {
  if (!r.ok) {
    const body = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(body.detail || body.error?.message || r.statusText);
  }
  return r.json();
};
export const api = {
  health: () => fetch("/api/system/health").then(json),
  stylePresets: () => fetch("/api/style-presets").then(json<StylePreset[]>),
  projects: (query = "") =>
    fetch(`/api/projects${query}`).then(json<Project[]>),
  project: (id: string) => fetch(`/api/projects/${id}`).then(json<Project>),
  createProject: (body: unknown) =>
    fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<Project>),
  updateProject: (id: string, body: unknown) =>
    fetch(`/api/projects/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<Project>),
  deleteProject: (id: string) =>
    fetch(`/api/projects/${id}`, { method: "DELETE" }).then((r) => {
      if (!r.ok) return json<never>(r);
    }),
  assets: (id: string) =>
    fetch(`/api/projects/${id}/assets`).then(json<Asset[]>),
  upload: (
    id: string,
    role: string,
    file: File,
    onProgress?: (n: number) => void,
  ) =>
    new Promise<Asset>((resolve, reject) => {
      const x = new XMLHttpRequest();
      x.open(
        "POST",
        `/api/projects/${id}/assets?role=${encodeURIComponent(role)}`,
      );
      x.upload.onprogress = (e) =>
        e.lengthComputable &&
        onProgress?.(Math.round((e.loaded / e.total) * 100));
      x.onload = () =>
        x.status < 300
          ? resolve(JSON.parse(x.responseText))
          : reject(new Error(JSON.parse(x.responseText)?.detail || "上传失败"));
      x.onerror = () => reject(new Error("网络错误"));
      const f = new FormData();
      f.append("file", file);
      x.send(f);
    }),
  validate: (id: string) =>
    fetch(`/api/projects/${id}/validate`, { method: "POST" }).then(
      json<Validation>,
    ),
  validation: (id: string) =>
    fetch(`/api/projects/${id}/validation`).then(json<Validation>),
  acceptRisks: (id: string) =>
    fetch(`/api/projects/${id}/validation/accept-risks`, {
      method: "POST",
    }).then(json<Validation>),
  plan: (id: string) => fetch(`/api/projects/${id}/plan`).then(json),
  updatePlan: (id: string, body: unknown) =>
    fetch(`/api/projects/${id}/plan`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json),
  createJob: (id: string) =>
    fetch(`/api/projects/${id}/jobs`, { method: "POST" }).then(json<Job>),
  job: (id: string) => fetch(`/api/jobs/${id}`).then(json<Job>),
  retry: (id: string) =>
    fetch(`/api/jobs/${id}/retry`, { method: "POST" }).then(json<Job>),
  cancel: (id: string) =>
    fetch(`/api/jobs/${id}/cancel`, { method: "POST" }).then(json<Job>),
  confirmGeometry: (id: string) =>
    fetch(`/api/jobs/${id}/confirm-geometry`, { method: "POST" }).then(
      json<Job>,
    ),
  versions: (id: string) =>
    fetch(`/api/projects/${id}/versions`).then(json<Version[]>),
  version: (id: string) => fetch(`/api/versions/${id}`).then(json<Version>),
  exportStl: (
    id: string,
    body: {
      filename: string;
      scope: "all" | "visible";
      unit: "mm" | "cm" | "m";
      applyModifiers: boolean;
      targetHeightMm?: number;
    },
  ) =>
    fetch(`/api/versions/${id}/exports/stl`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(
      json<{
        filename: string;
        url: string;
        byteSize: number;
        sourceType: string;
        engine: string;
        unit: string;
        targetHeightMm?: number;
      }>,
    ),
  deleteVersion: (id: string) =>
    fetch(`/api/versions/${id}`, { method: "DELETE" }).then((r) => {
      if (!r.ok) return json<never>(r);
    }),
  setBaseVersion: (id: string) =>
    fetch(`/api/versions/${id}/set-base`, { method: "POST" }).then(
      json<Version>,
    ),
  decide: (id: string, decision: string, notes: string) =>
    fetch(`/api/versions/${id}/${decision}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes }),
    }).then(json),
  revise: (id: string, body: unknown) =>
    fetch(`/api/versions/${id}/revisions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json),
  refinementModules: () =>
    fetch("/api/refinement/modules").then(
      json<
        Record<
          string,
          {
            label: string;
            capability: string;
            description: string;
            dependencies?: string[];
          }
        >
      >,
    ),
  createRefinement: (body: unknown) =>
    fetch("/api/refinement/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<RefinementJob>),
  refinement: (id: string) =>
    fetch(`/api/refinement/jobs/${id}`).then(json<RefinementJob>),
  cancelRefinement: (id: string) =>
    fetch(`/api/refinement/jobs/${id}/cancel`, { method: "POST" }).then(
      json<RefinementJob>,
    ),
  refinements: (id: string) =>
    fetch(`/api/projects/${id}/refinement-jobs`).then(json<RefinementJob[]>),
  comments: (id: string) =>
    fetch(`/api/versions/${id}/comments`).then(json<VersionComment[]>),
  createComment: (id: string, body: unknown) =>
    fetch(`/api/versions/${id}/comments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<VersionComment>),
  replyComment: (id: string, body: string) =>
    fetch(`/api/comments/${id}/replies`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body }),
    }).then(json<VersionComment>),
  closeComment: (id: string) =>
    fetch(`/api/comments/${id}/close`, { method: "POST" }).then(
      json<VersionComment>,
    ),
  reopenComment: (id: string) =>
    fetch(`/api/comments/${id}/reopen`, { method: "POST" }).then(
      json<VersionComment>,
    ),
  attachComment: (id: string, viewRole: string, file: File) => {
    const f = new FormData();
    f.append("file", file);
    return fetch(
      `/api/comments/${id}/attachments?viewRole=${encodeURIComponent(viewRole)}&purpose=auxiliary_reference`,
      { method: "POST", body: f },
    ).then(json<VersionComment>);
  },
  revisionPlan: (body: unknown) =>
    fetch("/api/revisions/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json),
  createRevision: (body: unknown) =>
    fetch("/api/revisions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<RevisionRequest>),
  revision: (id: string) =>
    fetch(`/api/revisions/${id}`).then(json<RevisionRequest>),
  reviewRevisionComment: (
    rid: string,
    cid: string,
    resultStatus: string,
    notes = "",
  ) =>
    fetch(`/api/revisions/${rid}/comments/${cid}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resultStatus, notes }),
    }).then(json<RevisionRequest>),
  createDetailPlan: (projectId: string, mode = "balanced") =>
    fetch(`/api/projects/${projectId}/detail-plans`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    }).then(json<DetailPlan>),
  detailPlan: (id: string) =>
    fetch(`/api/detail-plans/${id}`).then(json<DetailPlan>),
  updateDetailRegion: (planId: string, regionId: string, body: unknown) =>
    fetch(`/api/detail-plans/${planId}/regions/${regionId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<DetailPlan>),
  confirmDetailPlan: (id: string) =>
    fetch(`/api/detail-plans/${id}/confirm`, { method: "POST" }).then(
      json<DetailPlan>,
    ),
  createDetailJob: (id: string, candidateCount = 2) =>
    fetch(`/api/detail-plans/${id}/jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ candidateCount }),
    }).then(json<DetailJob>),
  detailJob: (id: string) =>
    fetch(`/api/detail-jobs/${id}`).then(json<DetailJob>),
  cancelDetailJob: (id: string) =>
    fetch(`/api/detail-jobs/${id}/cancel`, { method: "POST" }).then(
      json<DetailJob>,
    ),
  retryDetailJob: (id: string) =>
    fetch(`/api/detail-jobs/${id}/retry`, { method: "POST" }).then(
      json<DetailJob>,
    ),
  approveDetailGroup: (id: string, notes = "") =>
    fetch(`/api/detail-candidate-groups/${id}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes }),
    }).then(json),
  rejectDetailGroup: (id: string, notes = "") =>
    fetch(`/api/detail-candidate-groups/${id}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes }),
    }).then(json),
  referenceConsumption: (id: string) =>
    fetch(`/api/reference-sets/${id}/consumption-map`).then(json),
  createPartJob: (body: {partId:string;overlap:number;quality?:string}) =>
    fetch("/api/parts/jobs", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})
      .then(json<{id:string;partId:string;status:string;progress:number;message:string;candidateUrl?:string;logs:string[];error?:string}>),
  partJob: (id:string) =>
    fetch(`/api/parts/jobs/${id}`).then(json<{id:string;partId:string;status:string;progress:number;message:string;candidateUrl?:string;logs:string[];error?:string}>),
};
