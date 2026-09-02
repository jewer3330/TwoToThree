"""selfreg 节点的 Remote 实现（v2：经 WS 命令通道执行，替代 SSH）。

worker.run 仍在控制面跑（持有 DB/素材/版本目录），需要 GPU 机执行 Hunyuan /
Blender 命令时，backends 的 generate_* 会拿到一个 Remote 并调用
prepare / run / download 等方法。SSH 节点用 backends.Remote（scp/ssh）；
selfreg 节点（NAT 后、AutoDL）无法 SSH 推入，用本类把同一套操作映射到
「WS run_cmd + HTTP pullbox 下发 + HTTP inbox 回传」：

  - prepare(marker, locals)：控制面把输入文件复制到 pullbox（本地目录）
  - run(...)                 ：dispatch run_cmd，agent 先 fetch 输入再本地
                               subprocess，stdout 逐行回传（log 回调）
  - download_* / upload     ：让 agent 把产物 POST 回控制面 inbox，
                               控制面从 inbox 读文件校验落库
  - stage/join/norm         ：路径是「节点本地视角」（agent 与 worker 约定
                               同一 work 根下 selfreg-stage/<marker>/...）
"""
from __future__ import annotations
import shutil
import time
import uuid
from pathlib import Path

from ..core import DATA


class SelfregRemote:
    """对齐 backends.Remote 所需接口的最小实现（selfreg 节点）。"""

    def __init__(self, node_id: str, node: dict | None = None) -> None:
        self.node_id = node_id
        node = node or {}
        os_name = (node.get('os') or 'linux').lower()
        self.os_type = 'windows' if os_name == 'windows' else 'linux'
        # 节点本地路径约定：work 根由 agent 上报（如 D:\print3d\work）
        self.work = str(node.get('workDir') or node.get('work') or '/root/autodl-tmp/print3d/work')
        self.stage_root = 'selfreg-stage'

    # ---- 路径（节点本地视角）----
    @property
    def is_windows(self) -> bool:
        return self.os_type == 'windows'

    @property
    def sep(self) -> str:
        return '\\' if self.is_windows else '/'

    def norm(self, p: str) -> str:
        return str(p).replace('/', '\\') if self.is_windows else str(p).replace('\\', '/')

    def join(self, *parts) -> str:
        out = []
        for i, p in enumerate(parts):
            if p in (None, '', '.'):
                continue
            s = self.norm(str(p))
            s = s.rstrip(self.sep) if i == 0 else s.strip(self.sep)
            if s:
                out.append(s)
        return self.sep.join(out)

    def stage(self, marker: str) -> str:
        """节点本地 stage 目录（相对节点 work）。"""
        return self.join(self.work, self.stage_root, marker)

    # ---- pullbox（控制面→节点 输入下发）----
    def pullbox_root(self, marker: str) -> Path:
        return DATA / 'selfreg' / 'pullbox' / marker

    def prepare(self, marker: str, locals_: list[Path]):
        """把输入文件复制到控制面 pullbox（agent 执行前 fetch 到同路径）。"""
        root = self.pullbox_root(marker)
        root.mkdir(parents=True, exist_ok=True)
        for p in locals_:
            if p.exists():
                dest = root / p.name
                shutil.copyfile(str(p), str(dest))
        # 记录本 marker 的文件名（run 时让 agent fetch）
        (root / '.manifest').write_text('\n'.join(sorted(x.name for x in root.iterdir()
                                                          if x.name != '.manifest')),
                                        encoding='utf-8')
        # 清理过期 pullbox（保留 6h）
        base = DATA / 'selfreg' / 'pullbox'
        try:
            for d in list(base.iterdir())[:50]:
                try:
                    if time.time() - d.stat().st_mtime > 6 * 3600:
                        shutil.rmtree(d, ignore_errors=True)
                except Exception:
                    pass
        except Exception:
            pass

    # ---- 命令执行 ----
    def run(self, command: list[str], log, cancelled, timeout: int = 3600, marker: str = ''):
        from . import selfreg
        if marker:
            # 让 agent 先拉取 pullbox 输入到节点本地 stage
            selfreg.fetch_files_sync(self.node_id, marker, self.stage(marker), timeout=60)
        exit_code, error = selfreg.run_command_sync(
            self.node_id, command, timeout=timeout, log=log)
        if error:
            raise RuntimeError(f'selfreg 节点执行失败：{error}')
        if exit_code:
            raise RuntimeError(f'selfreg 节点命令退出码 {exit_code}')

    # ---- 产物回传（节点→控制面 inbox）----
    def _inbox_root(self, upload_id: str) -> Path:
        return DATA / 'selfreg' / 'inbox' / upload_id

    def upload_remote(self, remote_path: str, local_path: Path,
                      timeout: int = 600) -> Path:
        """请求 agent 上传 remote_path 到 inbox，然后本地取走。"""
        from . import selfreg
        ok, err = selfreg.upload_file_sync(self.node_id, remote_path, timeout=timeout)
        if not ok:
            raise RuntimeError(f'selfreg 产物回传失败：{err}')
        return local_path

    def download_file(self, remote_file: str, local_file: Path, expected_size=None,
                      expected_sha256=None, kind='file'):
        self._pull_single(remote_file, local_file)

    def download_compressed(self, remote_file: str, local_file: Path, expected_size=None,
                            expected_sha256=None, kind='glb'):
        # selfreg 通道不做压缩：直接回传原文件
        self._pull_single(remote_file, local_file)

    def download(self, remote_file: str, local_file: Path, expected_size=None,
                 expected_sha256=None, kind='file', legacy_scp: bool = True):
        self._pull_single(remote_file, local_file)

    def _pull_single(self, remote_file: str, local_file: Path):
        """agent 上传单个文件到 inbox → 控制面拷贝到 local_file。"""
        from . import selfreg
        local_file.parent.mkdir(parents=True, exist_ok=True)
        upload_id = f'up-{uuid.uuid4().hex[:12]}'
        ok, err = selfreg.upload_file_sync(self.node_id, remote_file,
                                           upload_id=upload_id)
        if not ok:
            raise RuntimeError(f'selfreg 产物回传失败：{err}')
        inbox = self._inbox_root(upload_id)
        files = sorted(inbox.iterdir()) if inbox.exists() else []
        if not files:
            raise RuntimeError(f'selfreg 产物未到达 inbox：{remote_file}')
        shutil.move(str(files[0]), str(local_file))

    # ---- 兼容性方法（探测/清理等，selfreg 走心跳，多为 no-op）----
    def cleanup(self, marker: str, committed: bool = False):
        # 控制面 pullbox 由 prepare 定时清理；节点 stage 保留到任务产物注册后
        # （v1 语义：committed 才删远端；selfreg 暂不删除，靠 48h 清理）
        pass

    def remote_metadata(self, remote_file: str) -> tuple[int | None, str | None]:
        # 无法远程计算（走 upload 后本地校验）；返回 None 让调用方跳过预校验
        return None, None

    def remote_archive_metadata(self, remote_dir: str) -> tuple[str, int | None, str | None]:
        return '', None, None

    def cmd(self, command, timeout: int = 25):
        from . import selfreg
        exit_code, error = selfreg.run_command_sync(self.node_id, list(command), timeout=timeout)
        if error:
            raise RuntimeError(error)
        return type('R', (), {'returncode': exit_code, 'stdout': '', 'stderr': error or ''})()

    def upload(self, local: Path, remote_abs: str):
        # v2 输入下发统一走 prepare（pullbox）；保留接口占位
        raise NotImplementedError('selfreg 输入下发走 prepare(pullbox)')
