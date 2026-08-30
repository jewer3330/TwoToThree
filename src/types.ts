export type ProjectStatus =
  | "draft"
  | "uploading"
  | "validating"
  | "needs_input"
  | "awaiting_confirmation"
  | "queued"
  | "generating_geometry"
  | "validating_glb"
  | "awaiting_geometry_confirmation"
  | "rendering_review"
  | "quality_failed"
  | "awaiting_manual_refine"
  | "processing_materials"
  | "optimizing_web"
  | "ready_for_review"
  | "revision_requested"
  | "completed"
  | "completed_with_notes"
  | "transfer_pending"
  | "failed"
  | "cancelled";
export interface GpuHost {
  id: string;
  name: string;
  host: string;
  user: string;
  key: string;
  root: string;
  ext: string;
  work: string;
  labels: string[];
  maxConcurrentJobs: number;
  enabled: boolean;
  createdAt: string;
  status: {
    online?: boolean;
    gpu?: string;
    memTotal?: number;
    memUsed?: number;
    diskFree?: number;
    latencyMs?: number;
    caps?: Record<string, boolean>;
    runningJobs?: number;
    lastProbeAt?: string;
    lastError?: string | null;
  };
}
export interface GpuQueueItem {
  id: string;
  project_id: string;
  status: string;
  created_at: string;
  current_stage: string | null;
  hostName: string;
}
export interface GpuQueueView {
  paused: boolean;
  counts: { queued: number; running: number };
  queued: GpuQueueItem[];
  running: GpuQueueItem[];
  recent: (GpuQueueItem & { completed_at?: string; error_summary?: string | null })[];
}
export interface GpuOverview {
  hostCount: number;
  online: number;
  enabled: number;
  gpuMemTotal: number;
  gpuMemUsed: number;
  runningJobs: number;
  queue: { queued: number; running: number };
}
export interface PrinterStatus {
  state: string;
  stateLabel: string;
  progress: number | null;
  nozzleTemp: number;
  nozzleTarget: number;
  bedTemp: number;
  bedTarget: number;
  chamberTemp: number;
  speedLevel: number;
  layerNum: number;
  totalLayers: number;
  wifiSignal: number;
  remainingSeconds: number;
  gcodeName: string;
  fanSpeed: number;
  hms: unknown[];
}
export interface Printer {
  id: string;
  name: string;
  model: string;
  ip: string;
  accessCode: string;
  serial: string;
  enabled: boolean;
  createdAt: string;
  status: {
    ok?: boolean;
    error?: string | null;
    probedAt?: string;
    status?: PrinterStatus;
  };
}
export interface PrinterOverview {
  printerCount: number;
  online: number;
  printing: number;
}
export type ModelStyle = "realistic" | "cartoon" | "chibi";
export interface StylePreset {
  id: ModelStyle;
  label: string;
  description: string;
  featurePrompt: string;
  negativePrompt: string;
  viewWeights: { front: number; side: number; back: number };
  depthScale: number;
  featureRelief: number;
}
export interface Project {
  id: string;
  slug: string;
  name: string;
  subjectType: "character" | "object" | "hybrid";
  intendedUse: "web" | "game" | "animation" | "hero-render";
  quality: string;
  modelStyle: ModelStyle;
  visualConditioningMode: "auto" | "original" | "contour" | "rgb_depth";
  status: ProjectStatus;
  currentJobId?: string;
  baseVersionId?: string;
  currentStage?: string;
  passedStages: number;
  totalStages: number;
  actualBackend?: string;
  thumbnailUrl?: string;
  createdAt: string;
  updatedAt: string;
}
export interface Asset {
  id: string;
  role: string;
  originalName: string;
  mimeType: string;
  byteSize: number;
  width?: number;
  height?: number;
  sha256: string;
  active: boolean;
  url?: string;
}
export interface ValidationCheck {
  code: string;
  label: string;
  status: "pass" | "warning" | "fail";
  evidence: string;
  affectedRegions?: string[];
}
export interface Validation {
  verdict: "pass" | "conditional" | "request_input" | "reject";
  checks: ValidationCheck[];
  risks: { code: string; message: string; consequence: string }[];
  acceptedAt?: string;
}
export interface Stage {
  id: string;
  label: string;
  status: string;
  startedAt?: string;
  completedAt?: string;
  duration?: string;
}
export interface Job {
  id: string;
  projectId: string;
  versionId: string;
  status: string;
  requestedBackend: string;
  actualBackend?: string;
  currentStage?: string;
  attempt: number;
  stages: Stage[];
  logs: string[];
  artifacts: Artifact[];
}
export interface Artifact {
  id: string;
  type: string;
  label: string;
  url: string;
  mimeType: string;
  byteSize: number;
  sha256: string;
  metadata: Record<string, unknown>;
}
export interface Version {
  id: string;
  projectId: string;
  number: number;
  label: string;
  status: string;
  isBase: boolean;
  model?: Artifact;
  createdAt: string;
  qualityReport?: QualityReport;
}
export interface QualityReport {
  scores: Record<string, number>;
  stats: Record<string, number | string>;
  differences: { severity: string; message: string }[];
  approximations: { region: string; confidence: number; note: string }[];
}
export interface RefinementJob {
  id: string;
  projectId: string;
  sourceVersionId: string;
  outputVersionId?: string;
  status: string;
  config: {
    modules: string[];
    instructions: string;
    geometryRepairStrength: string;
    uvStrategy: string;
    uvIslandMargin: number;
    materialTemplate: string;
    targetTriangleRange: number[];
    textureResolution: number;
    maxWebGlbMB: number;
    preserveThickness: boolean;
    maxThicknessLoss: number;
    maxDecimationPerPass: number;
    minThinAxisRatio: number;
  };
  moduleStates: Record<string, string>;
  logs: string[];
  artifacts: Artifact[];
  qualityReport?: Record<string, unknown>;
  blenderVersion?: string;
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  errorSummary?: string;
}
export interface VersionComment {
  id: string;
  projectId: string;
  versionId: string;
  number: number;
  title: string;
  description: string;
  category: string;
  severity: string;
  status: string;
  recommendedRoute: string;
  meshName?: string;
  position?: { x: number; y: number; z: number };
  normal?: { x: number; y: number; z: number };
  cameraSnapshot?: Record<string, unknown>;
  screenshotUrl?: string;
  createdAt: string;
  updatedAt: string;
  replies: {
    id: string;
    authorType: string;
    body: string;
    createdAt: string;
  }[];
  attachments: {
    id: string;
    assetId: string;
    viewRole: string;
    purpose: string;
    name: string;
    url: string;
  }[];
}
export interface ReferenceSet {
  id: string;
  projectId: string;
  number: number;
  status: string;
  consistencyReport: Record<string, unknown>;
  lockedAt?: string;
  assets: {
    assetId: string;
    viewRole: string;
    purpose: string;
    sourceCommentId?: string;
    name: string;
    url: string;
  }[];
}
export interface RevisionRequest {
  id: string;
  projectId: string;
  sourceVersionId: string;
  outputVersionId?: string;
  referenceSet: ReferenceSet;
  status: string;
  route: string;
  config: Record<string, unknown>;
  logs: string[];
  errorSummary?: string;
  comments: (VersionComment & {
    resultStatus?: string;
    resultNotes?: string;
  })[];
}
export interface DetailRegion {
  id: string;
  regionKey: string;
  visibleViews: string[];
  coverageScore: number;
  clarityScore: number;
  consistencyScore: number;
  evidenceLevel: "observed" | "constrained" | "inferred" | "designed";
  targetUsage: "geometry" | "normal_displacement" | "material";
  riskLevel: "low" | "medium" | "high";
  recommendedViews: string[];
  constraints: Record<string, unknown>;
  selected: boolean;
}
export interface DetailPlan {
  id: string;
  projectId: string;
  sourceReferenceSetId: string;
  status: string;
  mode: "conservative" | "balanced" | "creative";
  analyzerVersion: string;
  summary: Record<string, unknown>;
  createdAt: string;
  confirmedAt?: string;
  regions: DetailRegion[];
}
export interface DetailCandidateGroup {
  id: string;
  regionId: string;
  regionKey: string;
  groupIndex: number;
  status: string;
  evidenceLevel: string;
  targetUsage: string;
  referenceSetId?: string;
  consistencyMetrics: Record<string, unknown>;
  reviewedAt?: string;
  reviewNote?: string;
  assets: {
    assetId: string;
    viewRole: string;
    name: string;
    url: string;
    sha256: string;
  }[];
}
export interface DetailJob {
  id: string;
  projectId: string;
  detailPlanId: string;
  status: string;
  provider: string;
  model?: string;
  workflowVersion?: string;
  seed: number;
  parameters: Record<string, unknown>;
  createdAt: string;
  progress: {
    current: number;
    total: number;
    percent: number;
    message?: string;
  };
  logs: string[];
  groups: DetailCandidateGroup[];
  errorMessage?: string;
}
