"""Explicit optional local video setup; no service starts and no videos upload.

Installs only a separate .venv-video and downloads one pinned Google model over
verified HTTPS. Never falls back to a mirror at runtime. Existing models must
match; no unknown file is overwritten. FFmpeg must already be installed.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
MODEL_URL='https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task'
MODEL_SHA256='5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1'
# SHA-256 observed on user's Mac on 2026-10-30: independently downloaded over HTTPS
# from MODEL_URL and byte-compared with locally loadable model (OFFICIAL_FILE_MATCH).
# The assistant's GitHub environment did not independently download these bytes.
# Keep strict SHA-256 verification and refuse to overwrite mismatching models.


def main():
    if sys.version_info<(3,12):
        print('Python 3.12+ required. No service started.');return 1
    if not all(shutil.which(tool) for tool in ('ffmpeg','ffprobe')):
        print('FFmpeg/ffprobe missing. On Mac with Homebrew, install ffmpeg first. No service started.');return 1
    target=ROOT/'.venv-video';python=target/'bin/python'
    model=ROOT/'assets/models/pose_landmarker_full.task'
    if model.exists() and hashlib.sha256(model.read_bytes()).hexdigest()!=MODEL_SHA256:
        print('Existing model hash differs; refusing to overwrite. Review its provenance first.');return 1
    try:
        if not python.exists():subprocess.run([sys.executable,'-m','venv',str(target)],check=True)
        subprocess.run([str(python),'-m','pip','install','-r',str(ROOT/'requirements-video.txt')],check=True)
        if not model.exists():
            model.parent.mkdir(parents=True,exist_ok=True)
            with urllib.request.urlopen(MODEL_URL,timeout=60) as response:
                data=response.read(16*1024*1024+1)
            if len(data)>16*1024*1024 or hashlib.sha256(data).hexdigest()!=MODEL_SHA256:
                raise ValueError('Model verification failed')
            with tempfile.NamedTemporaryFile(dir=model.parent,delete=False) as file:
                temporary=Path(file.name);file.write(data)
            try:os.replace(temporary,model)
            finally:temporary.unlink(missing_ok=True)
        subprocess.run([str(python),'-c','import mediapipe,cv2,pydantic; print("Video runtime imports passed")'],check=True)
    except Exception:
        print('Video setup failed. Review local runtime/network requirements; no server or video upload was started.');return 1
    print('Optional video environment ready. Start the existing local console; models/videos are not committed.');return 0


if __name__=='__main__':raise SystemExit(main())
