"""Bounded subprocess adapter around existing MediaPipe/V4 algorithms.

Run only in .venv-video. Media/model files never downloaded at runtime. Original
upload is deleted after normalization, normalized preview expires with the job.
No user-provided path, filename, URL or command is accepted by the HTTP API.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess

MAX_BYTES = 25 * 1024 * 1024
MAX_SECONDS = 60
MAX_FRAMES = 720


class Rejected(ValueError):
    pass


def metadata(path):
    with path.open('rb') as file:data=file.read(32)
    if path.stat().st_size > MAX_BYTES or data[4:8] != b'ftyp':
        raise Rejected('unsupported_container')
    command = ['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-enable_drefs', '0',
        '-show_entries', 'format=duration,format_name:stream=codec_type,codec_name,width,height,avg_frame_rate,duration,nb_frames',
        '-of', 'json', str(path)]
    try:
        result = subprocess.run(command, capture_output=True, timeout=15, check=True)
        probe = json.loads(result.stdout)
        videos = [s for s in probe['streams'] if s['codec_type'] == 'video']
        if len(videos) != 1 or 'mov' not in probe['format']['format_name'].split(','):
            raise Rejected('unsupported_streams')
        video = videos[0]
        duration = float(probe['format']['duration'])
        num, den = video['avg_frame_rate'].split('/')
        fps = float(num) / float(den)
        width, height = int(video['width']), int(video['height'])
        if (not math.isfinite(duration) or not 0 < duration <= MAX_SECONDS
                or not math.isfinite(fps) or not 0 < fps <= 60
                or not 16 <= width <= 1920 or not 16 <= height <= 1920 or width*height > 2073600):
            raise Rejected('media_limits')
        if video['codec_name'] not in ('h264', 'hevc', 'mpeg4', 'h263', 'mjpeg'):
            raise Rejected('unsupported_codec')
        return {'duration_seconds': duration, 'fps': fps, 'width': width, 'height': height,
                'codec': video['codec_name'], 'analysis_fps': min(12.0, fps)}
    except Rejected:
        raise
    except Exception:
        raise Rejected('unreadable_video') from None


def normalize(original, preview, meta):
    # No playlists, network protocols or external MOV data references. Force MOV
    # demuxer, drop audio/metadata; bound output duration and spatial/temporal size.
    command = ['ffmpeg', '-nostdin', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-enable_drefs', '0',
        '-f', 'mov', '-i', str(original), '-map', '0:v:0', '-an', '-sn', '-dn', '-map_metadata', '-1',
        '-vf', "scale=w='min(720,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
        '-r', str(meta['analysis_fps']), '-t', '60', '-frames:v', str(MAX_FRAMES), '-c:v', 'libx264',
        '-threads', '2', '-pix_fmt', 'yuv420p', '-preset', 'veryfast', '-movflags', '+faststart', '-y', str(preview)]
    try:
        subprocess.run(command, capture_output=True, check=True, timeout=60)
        if not preview.is_file() or preview.stat().st_size > MAX_BYTES:
            raise Rejected('normalized_size')
    except Rejected:
        raise
    except Exception:
        raise Rejected('normalization_failed') from None
    finally:
        original.unlink(missing_ok=True)


def analyze(job_dir, model_path, side, job_id):
    original, preview = job_dir/'upload.bin', job_dir/'preview.mp4'
    meta = metadata(original)
    normalize(original, preview, meta)
    from tools.video_analysis.pose_extractor import extract_video_pose
    from tools.video_analysis.event_detection import detect_changes
    from tools.video_analysis.event_review import build_review_records
    try:
        pose = extract_video_pose(str(preview), side=side, max_frames=MAX_FRAMES,
                                  model_path=str(model_path), include_keypoints=True)
    except Exception:
        raise Rejected('pose_runtime_failed') from None
    if not pose.frames:
        raise Rejected('no_decodable_frames')
    source = {'mode': 'real', 'is_mock': False, 'model': 'mediapipe_pose',
              'video_path': 'local-video://' + job_id, 'fps': pose.source['fps'], 'side': side}
    frames = [f.model_dump() for f in pose.frames]
    points = [f.model_dump() for f in pose.keypoints]
    for f in points:
        f['source'] = source['video_path']
    # Reject nonfinite exports rather than turn bad coordinates into evidence.
    detection = detect_changes(frames, source=source, is_mock=False)
    review = build_review_records(detection.model_dump(), 'local-analysis://' + job_id)
    result = dict(schema_version='local-video-v2', is_mock=False, source=source, metadata=meta,
        frames=frames, keypoints=points, quality=pose.summary, detection=detection.model_dump(),
        review=review.model_dump(mode='json'), review_verification='local_unverified',
        authenticated_coach=False, technical_error_assessment='not_assessed',
        limitations=['单人、固定侧面视角的二维观测；视频不是专业花滑动作评价验证集。',
            '按不高于12fps和720像素边长重采样，帧号对应分析预览；时间为预览毫秒，不是原始帧号。',
            '未检出保持缺失；低可见度和二维投影不能证明真实重心、冰刀用刃或技术错误。',
            'V4阈值为探索性变化检测参数，尚待专项教练确认；零事件不等于动作正确。'])
    payload = json.dumps(result, ensure_ascii=False, allow_nan=False)
    if len(payload.encode()) > 20*1024*1024:
        raise Rejected('analysis_output_limit')
    (job_dir/'result.tmp').write_text(payload, encoding='utf-8')
    (job_dir/'result.tmp').replace(job_dir/'result.json')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job-dir', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--side', choices=['left','right'], required=True)
    args = parser.parse_args()
    # Best-effort POSIX resource caps; decoding/inference also have wall-clock
    # deadlines in the parent. No preexec_fn is run from a multithreaded server.
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU,(150,155))
        resource.setrlimit(resource.RLIMIT_FSIZE,(32*1024*1024,32*1024*1024))
    except (ImportError,ValueError,OSError):pass
    try:
        analyze(args.job_dir, args.model, args.side, args.job_id)
        return 0
    except Exception as error:
        reason = str(error) if isinstance(error, Rejected) else 'analysis_failed'
        (args.job_dir/'error.json').write_text(json.dumps({'code':reason}))
        for name in ('upload.bin','preview.mp4','result.tmp','result.json'):
            (args.job_dir/name).unlink(missing_ok=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
