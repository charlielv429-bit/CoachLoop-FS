"""Regression checks for the Mac-verified Google Pose Landmarker digest.

These tests do not constitute a second independent download from Google.
"""
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_DIGEST = "5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1"
OFFICIAL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task"


def load_setup():
    return runpy.run_path(str(ROOT / "scripts/setup_local_video.py"), run_name="test_import")


def test_pinned_upstream_source_and_user_verified_hash():
    module = load_setup()
    assert module["MODEL_URL"] == OFFICIAL_URL
    assert module["MODEL_SHA256"] == UPSTREAM_DIGEST


def test_existing_mismatched_model_is_not_overwritten(tmp_path, monkeypatch):
    module = load_setup()
    model = tmp_path / "assets" / "models" / "pose_landmarker_full.task"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"corrupted-or-unverified-model")
    monkeypatch.setitem(module["main"].__globals__, "ROOT", tmp_path)
    monkeypatch.setattr(module["shutil"], "which", lambda _: "/usr/bin/mock-tool")
    before = model.read_bytes()
    assert module["main"]() == 1
    assert model.read_bytes() == before
    assert not (tmp_path / ".venv-video").exists()
