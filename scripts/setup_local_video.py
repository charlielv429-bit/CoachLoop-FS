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
MODEL_SHA256='4eaa5eb7a98365221087693fcc286334cf0858e2eb6e15b506aa4a7ecdcec4ad'
# Hash observed from the recorded public mirror; downloading DIRECTLY from Google
# and matching it is the user's independent upstream comparison, not a claim that
# this execution environment already reached Google. See video-v20.md provenance.


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
