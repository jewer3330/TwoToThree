import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

export interface AnnotationSnapshot {
  meshName: string;
  position: { x: number; y: number; z: number };
  normal: { x: number; y: number; z: number };
  cameraSnapshot: Record<string, unknown>;
  screenshotDataUrl: string;
}
export interface ViewportCameraState {
  position: [number, number, number];
  target: [number, number, number];
}
interface Props {
  url: string;
  onStats: (s: Record<string, number | string>) => void;
  onSelect: (name: string) => void;
  onAnnotate?: (data: AnnotationSnapshot) => void;
  cameraState?: ViewportCameraState;
  onCameraChange?: (state: ViewportCameraState) => void;
  comparisonMode?: boolean;
}

export default function ModelViewport({
  url,
  onStats,
  onSelect,
  onAnnotate,
  cameraState,
  onCameraChange,
  comparisonMode = false,
}: Props) {
  const host = useRef<HTMLDivElement>(null),
    callbacks = useRef({ onStats, onSelect, onAnnotate, onCameraChange }),
    api = useRef<any>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(0);
  callbacks.current = { onStats, onSelect, onAnnotate, onCameraChange };
  useEffect(() => {
    if (!host.current) return;
    const el = host.current,
      scene = new THREE.Scene();
    scene.background = new THREE.Color(0x111820);
    const camera = new THREE.PerspectiveCamera(
      30,
      el.clientWidth / el.clientHeight,
      0.01,
      1000,
    );
    camera.position.set(3, 2.3, 6);
    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      preserveDrawingBuffer: true,
    });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setSize(el.clientWidth, el.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    el.appendChild(renderer.domElement);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    scene.add(new THREE.HemisphereLight(0xd9e9ff, 0x263141, 2.5));
    const key = new THREE.DirectionalLight(0xffffff, 4);
    key.position.set(4, 7, 5);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x755cff, 3);
    rim.position.set(-5, 4, -4);
    scene.add(rim);
    scene.add(new THREE.GridHelper(20, 30, 0x334255, 0x202a36));
    let model: THREE.Object3D | undefined,
      auto = false,
      gray = false,
      wire = false,
      disposed = false;
    const download = new AbortController();
    const originals = new Map<THREE.Mesh, THREE.Material | THREE.Material[]>(),
      grayMat = new THREE.MeshStandardMaterial({
        color: 0xaab2bd,
        roughness: 0.72,
      });
    setError("");
    setLoading(0);
    const loadModel = async () => {
      try {
        const response = await fetch(url, {
          signal: download.signal,
          credentials: "same-origin",
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const total = Number(response.headers.get("content-length")) || 0;
        const reader = response.body?.getReader();
        let buffer: ArrayBuffer;
        if (reader) {
          const chunks: Uint8Array[] = [];
          let loaded = 0;
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            chunks.push(value);
            loaded += value.byteLength;
            if (total) setLoading(Math.min(99, Math.round((loaded / total) * 100)));
          }
          const bytes = new Uint8Array(loaded);
          let offset = 0;
          for (const chunk of chunks) {
            bytes.set(chunk, offset);
            offset += chunk.byteLength;
          }
          buffer = bytes.buffer;
        } else {
          buffer = await response.arrayBuffer();
        }
        if (disposed) return;
        const resourceBase = new URL(".", response.url).href;
        new GLTFLoader().parse(buffer, resourceBase, (g) => {
        if (disposed) return;
        model = g.scene;
        let vertices = 0,
          triangles = 0;
        const materials = new Set<THREE.Material>(),
          textures = new Set<THREE.Texture>();
        model.traverse((o) => {
          if ((o as THREE.Mesh).isMesh) {
            const m = o as THREE.Mesh;
            originals.set(m, m.material);
            vertices += m.geometry.attributes.position?.count || 0;
            triangles += m.geometry.index
              ? m.geometry.index.count / 3
              : (m.geometry.attributes.position?.count || 0) / 3;
            (Array.isArray(m.material) ? m.material : [m.material]).forEach(
              (mat) => {
                materials.add(mat);
                Object.values(mat).forEach(
                  (v) =>
                    (v as any)?.isTexture && textures.add(v as THREE.Texture),
                );
              },
            );
          }
        });
        const box = new THREE.Box3().setFromObject(model),
          size = box.getSize(new THREE.Vector3()),
          center = box.getCenter(new THREE.Vector3()),
          scale = 4 / Math.max(size.y, 0.001);
        model.scale.setScalar(scale);
        model.position.set(
          -center.x * scale,
          -box.min.y * scale,
          -center.z * scale,
        );
        scene.add(model);
        controls.target.set(0, 2, 0);
        controls.update();
        callbacks.current.onStats({
          vertices: Math.round(vertices),
          triangles: Math.round(triangles),
          materials: materials.size,
          textures: textures.size,
        });
        setLoading(100);
        }, (e) => {
          if (!disposed) setError(`GLB 加载失败：${e instanceof Error ? e.message : "文件不可解析"}`);
        });
      } catch (e) {
        if (!disposed && !(e instanceof DOMException && e.name === "AbortError")) {
          setError(`GLB 加载失败：${e instanceof Error ? e.message : "文件不可解析"}`);
        }
      }
    };
    void loadModel();
    const applyCamera = (state: ViewportCameraState) => {
      auto = false;
      camera.position.fromArray(state.position);
      controls.target.fromArray(state.target);
      controls.update();
    };
    const view = (x: number, y: number, z: number) => {
      const state: ViewportCameraState = {
        position: [x, y, z],
        target: [0, 2, 0],
      };
      applyCamera(state);
      callbacks.current.onCameraChange?.(state);
    };
    const controlsEnd = () =>
      callbacks.current.onCameraChange?.({
        position: camera.position.toArray() as [number, number, number],
        target: controls.target.toArray() as [number, number, number],
      });
    controls.addEventListener("end", controlsEnd);
    api.current = {
      view,
      applyCamera,
      toggleAuto: () => (auto = !auto),
      toggleGray: () => {
        gray = !gray;
        originals.forEach(
          (mat, mesh) => (mesh.material = gray ? grayMat : mat),
        );
      },
      toggleWire: () => {
        wire = !wire;
        originals.forEach((mat) =>
          (Array.isArray(mat) ? mat : [mat]).forEach((m) => {
            (m as THREE.MeshStandardMaterial).wireframe = wire;
            m.needsUpdate = true;
          }),
        );
      },
      screenshot: () => {
        const a = document.createElement("a");
        a.download = "model-review.png";
        a.href = renderer.domElement.toDataURL("image/png");
        a.click();
      },
    };
    const ray = new THREE.Raycaster(),
      pointer = new THREE.Vector2();
    const click = (e: MouseEvent) => {
      if (!model) return;
      const r = renderer.domElement.getBoundingClientRect();
      pointer.set(
        ((e.clientX - r.left) / r.width) * 2 - 1,
        -((e.clientY - r.top) / r.height) * 2 + 1,
      );
      ray.setFromCamera(pointer, camera);
      const hit = ray.intersectObject(model, true)[0];
      callbacks.current.onSelect(hit?.object.name || "Root");
      if (hit && callbacks.current.onAnnotate) {
        const n =
          hit.face?.normal.clone().transformDirection(hit.object.matrixWorld) ||
          new THREE.Vector3();
        callbacks.current.onAnnotate({
          meshName: hit.object.name || "Root",
          position: { x: hit.point.x, y: hit.point.y, z: hit.point.z },
          normal: { x: n.x, y: n.y, z: n.z },
          cameraSnapshot: {
            position: camera.position.toArray(),
            target: controls.target.toArray(),
            zoom: camera.zoom,
          },
          screenshotDataUrl: renderer.domElement.toDataURL("image/png"),
        });
      }
    };
    renderer.domElement.addEventListener("dblclick", click);
    const resize = () => {
      camera.aspect = el.clientWidth / el.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(el.clientWidth, el.clientHeight);
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    renderer.setAnimationLoop(() => {
      if (auto && model) model.rotation.y += 0.004;
      controls.update();
      renderer.render(scene, camera);
    });
    return () => {
      disposed = true;
      download.abort();
      ro.disconnect();
      controls.removeEventListener("end", controlsEnd);
      renderer.setAnimationLoop(null);
      renderer.domElement.removeEventListener("dblclick", click);
      model?.traverse((object) => {
        const mesh = object as THREE.Mesh;
        if (!mesh.isMesh) return;
        mesh.geometry.dispose();
        (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).forEach((material) => {
          Object.values(material).forEach((value) => (value as THREE.Texture)?.isTexture && (value as THREE.Texture).dispose());
          material.dispose();
        });
      });
      renderer.dispose();
      grayMat.dispose();
      el.replaceChildren();
    };
  }, [url]);
  useEffect(() => {
    if (cameraState) api.current?.applyCamera(cameraState);
  }, [cameraState, url]);
  return (
    <div className="viewport">
      <div ref={host} />
      {loading < 100 && !error && (
        <div className="viewport-loading">
          <span style={{ width: `${loading}%` }} />
          正在加载真实 GLB · {loading}%
        </div>
      )}
      {error && <div className="viewport-error">{error}</div>}
      <div className="viewport-tools">
        <button onClick={() => api.current?.view(0, 2.1, 7)}>正面</button>
        <button onClick={() => api.current?.view(7, 2.1, 0)}>侧面</button>
        <button onClick={() => api.current?.view(0, 2.1, -7)}>背面</button>
        <button onClick={() => api.current?.view(5, 2.5, 5)}>3/4</button>
        <i />
        {!comparisonMode && (
          <button onClick={() => api.current?.toggleAuto()}>自动旋转</button>
        )}
        <button onClick={() => api.current?.toggleGray()}>灰模</button>
        <button onClick={() => api.current?.toggleWire()}>线框</button>
        <button onClick={() => api.current?.screenshot()}>截图</button>
        <small>
          {comparisonMode ? "左右相机已同步" : "双击模型创建标注点"}
        </small>
      </div>
    </div>
  );
}
