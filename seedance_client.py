"""Seedance 2.5 White-Model Control HTTP 래퍼 (provider-agnostic 스켈레톤).

실제 API 스펙(엔드포인트/필드명/인증)은 릴리스 시점이 knowledge cutoff 이후라 확정 불가.
공식 문서 확인 후 seedance_config.json 채우면 즉시 사용 가능한 형태로 격리.

용법:
  # dry-run: 실전송 없이 조립된 request만 출력
  python seedance_client.py --payload out/s001_payload.json --config seedance_config.json

  # 실전송
  set SEEDANCE_API_KEY=...
  python seedance_client.py --payload out/s001_payload.json --config seedance_config.json --send

  # 자체 검증
  python seedance_client.py --demo

지원 업로드 모드 (config.upload.mode):
  - multipart      : multipart/form-data 로 FBX 등 직전송
  - inline_base64  : 파일을 base64 문자열로 JSON body에 인라인 (소용량)
  - presigned      : 별도 signed URL 획득 후 PUT 업로드 (미구현 스텁 — provider별 다름)

stdlib만 사용. requests 등 외부 의존 없음.
"""

from __future__ import annotations
import argparse
import base64
import io
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


REQUIRED_CONFIG_KEYS = ("endpoint", "auth", "field_mapping", "upload", "polling")
TODO_PREFIXES = ("http://TODO", "https://TODO")


class ConfigError(RuntimeError):
    pass


# ---- config --------------------------------------------------------------

def load_config(path: Path) -> dict:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    for k in REQUIRED_CONFIG_KEYS:
        if k not in cfg:
            raise ConfigError(f"config에 필수 키 없음: '{k}'")
    if str(cfg["endpoint"]).startswith(TODO_PREFIXES):
        raise ConfigError(
            f"endpoint 미설정: '{cfg['endpoint']}' — 공식 문서에서 실제 URL로 교체."
        )
    mode = cfg["upload"].get("mode")
    if mode not in {"multipart", "inline_base64", "presigned"}:
        raise ConfigError(f"upload.mode 값이 잘못됨: '{mode}'")
    return cfg


def build_auth_header(auth: dict) -> tuple[str, str]:
    env = auth.get("env_var") or "SEEDANCE_API_KEY"
    key = os.environ.get(env)
    if not key:
        raise ConfigError(f"환경변수 {env} 미설정. API key 넣고 재실행.")
    return auth.get("header_name", "Authorization"), f"{auth.get('prefix', 'Bearer ')}{key}"


# ---- 파일 인코딩 ---------------------------------------------------------

def _guess_mime(p: Path) -> str:
    mt, _ = mimetypes.guess_type(str(p))
    return mt or "application/octet-stream"


def _multipart_body(fields: dict, files: dict[str, Path]) -> tuple[bytes, str]:
    """stdlib만으로 multipart/form-data 조립. requests 미사용."""
    boundary = f"----claudeboundary{uuid.uuid4().hex}"
    buf = io.BytesIO()
    for name, value in fields.items():
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        buf.write(str(value).encode("utf-8"))
        buf.write(b"\r\n")
    for name, path in files.items():
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"upload 대상 없음: {p}")
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(
            f'Content-Disposition: form-data; name="{name}"; filename="{p.name}"\r\n'.encode()
        )
        buf.write(f"Content-Type: {_guess_mime(p)}\r\n\r\n".encode())
        buf.write(p.read_bytes())
        buf.write(b"\r\n")
    buf.write(f"--{boundary}--\r\n".encode())
    return buf.getvalue(), f"multipart/form-data; boundary={boundary}"


def _b64(path: Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


# ---- payload → API 필드 매핑 ---------------------------------------------

def map_payload(payload: dict, field_map: dict, mode: str, max_refs: int) -> tuple[dict, dict[str, Path]]:
    """seedance_builder payload → provider 형식 (fields, files) 로 리매핑."""
    fields: dict = {}
    files: dict[str, Path] = {}

    scalar_map = {
        "prompt":       payload.get("prompt"),
        "duration_sec": payload.get("duration_sec"),
        "aspect_ratio": payload.get("aspect_ratio"),
        "fps":          payload.get("fps"),
        "shot_id":      payload.get("shot_id"),
    }
    for our_key, val in scalar_map.items():
        if val is None:
            continue
        fields[field_map.get(our_key, our_key)] = val

    blockout = payload.get("blockout") or {}
    file_map = {
        "blockout_fbx":    blockout.get("fbx"),
        "blockout_obj":    blockout.get("obj"),
        "blockout_camera": blockout.get("camera_track"),
    }
    for our_key, path in file_map.items():
        if not path:
            continue
        api_key = field_map.get(our_key, our_key)
        if mode == "multipart":
            files[api_key] = Path(path)
        elif mode == "inline_base64":
            fields[api_key] = _b64(Path(path))
        elif mode == "presigned":
            fields[api_key + "__pending_upload__"] = str(path)

    refs = (payload.get("reference_images") or [])[:max_refs]
    ref_key = field_map.get("reference_images", "reference_images")
    if refs:
        if mode == "multipart":
            for i, r in enumerate(refs):
                files[f"{ref_key}[{i}]"] = Path(r)
        elif mode == "inline_base64":
            fields[ref_key] = [_b64(Path(r)) for r in refs]

    return fields, files


# ---- 조립 & 전송 ---------------------------------------------------------

def assemble_request(payload_path: Path, cfg: dict) -> dict:
    payload = json.loads(Path(payload_path).read_text(encoding="utf-8"))
    mode = cfg["upload"]["mode"]
    max_refs = int(cfg["upload"].get("max_reference_images", 50))
    fields, files = map_payload(payload, cfg["field_mapping"], mode, max_refs)
    return {
        "method": "POST",
        "url": cfg["endpoint"],
        "upload_mode": mode,
        "fields": fields,
        "files": {k: str(v) for k, v in files.items()},
    }


def send_request(payload_path: Path, cfg: dict) -> dict:
    payload = json.loads(Path(payload_path).read_text(encoding="utf-8"))
    mode = cfg["upload"]["mode"]
    max_refs = int(cfg["upload"].get("max_reference_images", 50))
    fields, files = map_payload(payload, cfg["field_mapping"], mode, max_refs)

    hn, hv = build_auth_header(cfg["auth"])
    headers = {hn: hv}

    if mode == "multipart":
        body, ctype = _multipart_body(fields, files)
        headers["Content-Type"] = ctype
    elif mode == "inline_base64":
        body = json.dumps(fields).encode("utf-8")
        headers["Content-Type"] = "application/json"
    else:  # presigned
        raise NotImplementedError(
            "presigned 모드는 provider별 별도 업로드 단계 필요. "
            "config.upload.presigned_endpoint로 signed URL 획득 → PUT 업로드 → payload에 URL만 참조하는 "
            "커스텀 구현 요망."
        )

    req = urllib.request.Request(cfg["endpoint"], data=body, method="POST", headers=headers)
    timeout = int(cfg["polling"].get("timeout_sec", 600))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.getcode()
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code

    try:
        body_json = json.loads(raw.decode("utf-8"))
    except Exception:
        body_json = {"_raw_text": raw.decode("utf-8", errors="replace")}
    return {"status_code": status, "body": body_json}


def poll_job(job_id: str, cfg: dict) -> dict:
    p = cfg["polling"]
    if p.get("mode") != "poll":
        raise ConfigError("polling.mode != 'poll' — 이 provider는 즉시 응답. poll_job 호출 부적절.")
    tpl = p.get("status_endpoint")
    if not tpl:
        raise ConfigError("polling.status_endpoint 미설정")
    url = tpl.replace("{job_id}", urllib.parse.quote(job_id))
    hn, hv = build_auth_header(cfg["auth"])
    status_field = p.get("status_field", "status")
    success = set(p.get("success_values", ["succeeded", "completed", "done"]))
    failure = set(p.get("failure_values", ["failed", "error", "cancelled"]))
    interval = int(p.get("interval_sec", 5))
    timeout = int(p.get("timeout_sec", 600))
    start = time.time()
    while True:
        req = urllib.request.Request(url, headers={hn: hv})
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        s = body.get(status_field)
        if s in success:
            return body
        if s in failure:
            raise RuntimeError(f"job failed: status={s} body={body}")
        if time.time() - start > timeout:
            raise TimeoutError(f"job {job_id} polling timeout after {timeout}s")
        time.sleep(interval)


# ---- CLI -----------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(prog="seedance_client")
    ap.add_argument("--payload", help="seedance_builder 산출 payload.json")
    ap.add_argument("--config", help="seedance_config.json 경로")
    ap.add_argument("--send", action="store_true", help="실전송. 없으면 dry-run.")
    ap.add_argument("--out", help="응답 저장 경로 (기본: <payload>_response.json)")
    ap.add_argument("--demo", action="store_true", help="자체 검증만 실행")
    args = ap.parse_args()

    if args.demo:
        _demo()
        return 0

    if not args.payload or not args.config:
        ap.error("--payload와 --config는 필수 (또는 --demo)")

    cfg = load_config(Path(args.config))
    payload_path = Path(args.payload)

    if not args.send:
        print(json.dumps(assemble_request(payload_path, cfg), indent=2, ensure_ascii=False))
        print("\n[dry-run] --send 없이 조립만. 실전송하려면 --send 추가.")
        return 0

    result = send_request(payload_path, cfg)
    out = Path(args.out) if args.out else payload_path.parent / (payload_path.stem + "_response.json")
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = 200 <= result["status_code"] < 300
    print(f"[send] status={result['status_code']} -> {out}")
    return 0 if ok else 1


# ---- 자체 검증 ------------------------------------------------------------

def _demo():
    import tempfile

    # 1) 필드 매핑
    payload = {
        "shot_id": "s001", "duration_sec": 8.0, "aspect_ratio": "16:9", "fps": 24,
        "prompt": "test prompt",
        "blockout": {"fbx": "nope.fbx", "obj": None, "camera_track": "nope.json"},
        "reference_images": [],
    }
    field_map = {
        "prompt": "text_prompt",
        "duration_sec": "duration",
        "aspect_ratio": "aspect",
        "fps": "fps",
        "shot_id": "external_id",
        "blockout_fbx": "model_file",
        "blockout_camera": "camera_track_file",
    }
    fields, files = map_payload(payload, field_map, "multipart", 50)
    assert fields["text_prompt"] == "test prompt", fields
    assert fields["external_id"] == "s001"
    assert fields["duration"] == 8.0
    assert fields["aspect"] == "16:9"
    assert "model_file" in files and "camera_track_file" in files
    assert "blockout_obj" not in files, "None 파일 스킵 실패"

    # 2) base64 인코딩 실제로 되나
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".fbx")
    tmp.write(b"fake fbx bytes"); tmp.close()
    p2 = dict(payload)
    p2["blockout"] = {"fbx": tmp.name, "obj": None, "camera_track": None}
    fields2, files2 = map_payload(p2, field_map, "inline_base64", 50)
    assert not files2, "inline_base64는 files에 아무것도 남기지 말아야"
    assert base64.b64decode(fields2["model_file"]) == b"fake fbx bytes"
    os.unlink(tmp.name)

    # 3) reference_images cap
    tmp_refs = []
    for _ in range(3):
        t = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        t.write(b"x"); t.close()
        tmp_refs.append(t.name)
    p3 = dict(payload)
    p3["reference_images"] = tmp_refs
    fields3, files3 = map_payload(p3, field_map, "multipart", max_refs=2)
    assert len([k for k in files3 if k.startswith("reference_images")]) == 2, "max_refs cap 실패"
    for f in tmp_refs:
        os.unlink(f)

    # 4) TODO endpoint 거부
    tc = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8")
    json.dump({
        "endpoint": "https://TODO/x",
        "auth": {}, "field_mapping": {},
        "upload": {"mode": "multipart"}, "polling": {"mode": "sync"},
    }, tc); tc.close()
    try:
        load_config(Path(tc.name))
    except ConfigError as e:
        assert "endpoint 미설정" in str(e), e
    else:
        raise AssertionError("TODO endpoint 거부 실패")
    os.unlink(tc.name)

    # 5) upload.mode 잘못된 값 거부
    tc2 = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8")
    json.dump({
        "endpoint": "https://api.example.com/x",
        "auth": {}, "field_mapping": {},
        "upload": {"mode": "carrier_pigeon"}, "polling": {"mode": "sync"},
    }, tc2); tc2.close()
    try:
        load_config(Path(tc2.name))
    except ConfigError as e:
        assert "upload.mode" in str(e)
    else:
        raise AssertionError("잘못된 upload.mode 거부 실패")
    os.unlink(tc2.name)

    # 6) 실제 example config에 대해 로드가 TODO로 잘 실패하는지
    ex = Path(__file__).resolve().parent / "seedance_config.example.json"
    if ex.exists():
        try:
            load_config(ex)
        except ConfigError as e:
            assert "endpoint 미설정" in str(e), e
        else:
            raise AssertionError("example config가 TODO로 거부 안됨")

    # 7) multipart body 조립 (bytes와 boundary 헤더 확인)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".fbx")
    tmp.write(b"DEADBEEF"); tmp.close()
    body, ctype = _multipart_body({"prompt": "hi"}, {"file": Path(tmp.name)})
    assert ctype.startswith("multipart/form-data; boundary=----claudeboundary")
    assert b"DEADBEEF" in body
    assert b'name="prompt"' in body and b'name="file"' in body
    os.unlink(tmp.name)

    print("seedance_client.py: OK")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ConfigError, NotImplementedError) as e:
        print(f"[config error] {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"[error] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
