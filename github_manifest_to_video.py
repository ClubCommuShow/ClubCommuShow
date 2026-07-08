#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable


def run(cmd: list[str]) -> None:
    print("RUN:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def download_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return resp.read()


def download_file(url: str, out_path: Path) -> None:
    data = download_bytes(url)
    out_path.write_bytes(data)


def url_exists(url: str) -> bool:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
        },
        method="HEAD",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            code = getattr(resp, "status", 200)
            return 200 <= code < 400
    except Exception:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "*/*",
                },
            )
            with urllib.request.urlopen(req) as resp:
                code = getattr(resp, "status", 200)
                return 200 <= code < 400
        except Exception:
            return False


def normalize_slug(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    buf = []
    for ch in text:
        if ch.isalnum():
            buf.append(ch.lower())
        else:
            buf.append("_")
    slug = "".join(buf)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")


def parse_repo(repo_or_manifest_url: str, default_branch: str) -> tuple[str, str, str]:
    parsed = urllib.parse.urlparse(repo_or_manifest_url)
    parts = [p for p in parsed.path.split("/") if p]
    if parsed.netloc not in {"github.com", "raw.githubusercontent.com"}:
        raise ValueError(f"Unsupported host: {parsed.netloc}")
    if parsed.netloc == "raw.githubusercontent.com":
        if len(parts) < 4:
            raise ValueError("raw.githubusercontent.com URL is too short")
        return parts[0], parts[1], parts[2]
    if len(parts) < 2:
        raise ValueError("GitHub repo URL is too short")
    owner = parts[0]
    repo = parts[1]
    branch = default_branch
    if len(parts) >= 4 and parts[2] in {"blob", "tree"}:
        branch = parts[3]
    return owner, repo, branch


def to_raw_manifest_url(manifest_url: str, default_branch: str) -> str:
    parsed = urllib.parse.urlparse(manifest_url)
    parts = [p for p in parsed.path.split("/") if p]
    if parsed.netloc == "raw.githubusercontent.com":
        return manifest_url
    if parsed.netloc != "github.com":
        return manifest_url
    if len(parts) >= 5 and parts[2] == "blob":
        owner = parts[0]
        repo = parts[1]
        branch = parts[3]
        rel = "/".join(parts[4:])
        return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{rel}"
    owner, repo, branch = parse_repo(manifest_url, default_branch)
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/data/roster_manifest.json"


def ffmpeg_normalize(src_path: Path, dst_path: Path, width: int, height: int, background: str) -> None:
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={background}"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src_path),
        "-vf",
        vf,
        str(dst_path),
    ]
    run(cmd)


def ffmpeg_build_video(frames_dir: Path, output_path: Path, fps: int, crf: int, gop: int, codec: str) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(frames_dir / "frame_%06d.png"),
        "-c:v",
        codec,
        "-pix_fmt",
        "yuv420p",
        "-crf",
        str(crf),
        "-g",
        str(gop),
        "-an",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    run(cmd)


def unique_preserve(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def poster_dir_candidates(category: str) -> list[str]:
    key = normalize_slug(category)
    mapping = {
        "eventposter": ["event", "eventposter", "event_poster"],
        "frontposter": ["front", "frontposter", "front_poster"],
        "sideposter": ["side", "sideposter", "side_poster"],
        "backposter": ["back", "backposter", "back_poster"],
        "notice": ["notice"],
        "menu": ["menu", "kanpe"],
        "kanpe": ["kanpe", "menu"],
    }
    return mapping.get(key, [key])


def portrait_dir_candidates(category: str) -> list[str]:
    key = normalize_slug(category)
    aliases = {
        "owner": ["owner"],
        "manager": ["manager"],
        "operator": ["operator"],
        "assistant": ["assistant"],
        "staffleader": ["staffleader", "staff_leader"],
        "staff": ["staff"],
        "castleader": ["castleader", "castleader", "cast_leader"],
        "uppercast": ["uppercast", "upper_cast"],
        "downercast": ["downercast", "downer_cast"],
        "condisionalcast": ["condisionalcast", "conditionalcast", "conditional_cast", "condisional_cast"],
    }
    return aliases.get(key, [key])


def candidate_image_urls(raw_base: str, item: dict, include_portraits: bool, include_posters: bool) -> list[str]:
    out: list[str] = []
    slot = item.get("slot")
    category = str(item.get("category", "")).strip()
    if slot is None or category == "":
        return out
    slot_name = f"slot{slot}"
    exts = ["png", "jpg", "jpeg", "webp"]

    if include_posters:
        for folder in poster_dir_candidates(category):
            for ext in exts:
                out.append(f"{raw_base}images/posters/{folder}/{slot_name}.{ext}")
                out.append(f"{raw_base}images/poster/{folder}/{slot_name}.{ext}")

    if include_portraits:
        for folder in portrait_dir_candidates(category):
            for ext in exts:
                out.append(f"{raw_base}images/portraits/{folder}/{slot_name}.{ext}")
                out.append(f"{raw_base}images/portrait/{folder}/{slot_name}.{ext}")
                out.append(f"{raw_base}images/members/{folder}/{slot_name}.{ext}")
                out.append(f"{raw_base}images/member/{folder}/{slot_name}.{ext}")
                out.append(f"{raw_base}images/roster/{folder}/{slot_name}.{ext}")
    return unique_preserve(out)


def manifest_entries(manifest: dict, include_portraits: bool, include_posters: bool) -> list[dict]:
    entries: list[dict] = []
    if include_portraits:
        members = manifest.get("members", [])
        if isinstance(members, list):
            for item in members:
                if not isinstance(item, dict):
                    continue
                if not item.get("enabled", False):
                    continue
                if not item.get("showPortrait", True):
                    continue
                entries.append(item)
    if include_posters:
        posters = manifest.get("posters", [])
        if isinstance(posters, list):
            for item in posters:
                if not isinstance(item, dict):
                    continue
                if not item.get("enabled", False):
                    continue
                entries.append(item)
    return entries


def resolve_urls_from_manifest(raw_base: str, manifest: dict, include_portraits: bool, include_posters: bool) -> tuple[list[str], list[str]]:
    entries = manifest_entries(manifest, include_portraits, include_posters)
    resolved: list[str] = []
    missing: list[str] = []
    for item in entries:
        candidates = candidate_image_urls(raw_base, item, include_portraits=True if item in manifest.get("members", []) else False, include_posters=True if item in manifest.get("posters", []) else False)
        found = None
        for candidate in candidates:
            if url_exists(candidate):
                found = candidate
                break
        label = f"{item.get('category','?')} slot={item.get('slot','?')}"
        if found is None:
            missing.append(label)
        else:
            resolved.append(found)
    return unique_preserve(resolved), missing


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a video directly from a GitHub repo + roster_manifest.json.")
    parser.add_argument("--repo-url", required=True, help="GitHub repo URL, e.g. https://github.com/owner/repo/")
    parser.add_argument("--manifest-url", default="", help="GitHub blob/raw URL for roster_manifest.json. Omit to use /data/roster_manifest.json")
    parser.add_argument("--output", required=True, help="Output mp4 path")
    parser.add_argument("--branch", default="main", help="Default branch if URL does not specify it")
    parser.add_argument("--include-posters", action="store_true", help="Include posters from manifest")
    parser.add_argument("--include-portraits", action="store_true", help="Include portraits from manifest")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--crf", type=int, default=10)
    parser.add_argument("--gop", type=int, default=1)
    parser.add_argument("--codec", default="libx264")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--background", default="black")
    parser.add_argument("--save-url-list", default="", help="Optional path to save resolved URLs")
    parser.add_argument("--keep-workdir", action="store_true")
    args = parser.parse_args()
    if not args.include_posters and not args.include_portraits:
        args.include_posters = True
        args.include_portraits = True
    return args


def main() -> int:
    args = parse_args()
    owner, repo, branch = parse_repo(args.repo_url, args.branch)
    raw_base = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/"
    manifest_source = args.manifest_url.strip() or f"https://github.com/{owner}/{repo}/blob/{branch}/data/roster_manifest.json"
    raw_manifest_url = to_raw_manifest_url(manifest_source, args.branch)

    print(f"Repo: {owner}/{repo}")
    print(f"Branch: {branch}")
    print(f"Manifest: {raw_manifest_url}")

    try:
        manifest = json.loads(download_bytes(raw_manifest_url).decode("utf-8"))
    except Exception as exc:
        print(f"Failed to read manifest: {exc}", file=sys.stderr)
        return 1

    urls, missing = resolve_urls_from_manifest(raw_base, manifest, args.include_portraits, args.include_posters)
    if not urls:
        print("No image URLs resolved from manifest.", file=sys.stderr)
        if missing:
            print("Missing entries:", file=sys.stderr)
            for item in missing:
                print(f"  - {item}", file=sys.stderr)
        return 2

    print(f"Resolved images: {len(urls)}")
    if missing:
        print(f"Unresolved entries: {len(missing)}")
        for item in missing[:20]:
            print(f"MISS: {item}")

    if args.save_url_list:
        Path(args.save_url_list).write_text("\n".join(urls) + "\n", encoding="utf-8")

    workdir_obj = tempfile.TemporaryDirectory(prefix="github_manifest_to_video_")
    workdir = Path(workdir_obj.name)
    download_dir = workdir / "downloads"
    frames_dir = workdir / "frames"
    download_dir.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=True)
    print(f"Workdir: {workdir}")

    for idx, url in enumerate(urls):
        download_path = download_dir / f"src_{idx:06d}"
        frame_path = frames_dir / f"frame_{idx + 1:06d}.png"
        try:
            download_file(url, download_path)
            ffmpeg_normalize(download_path, frame_path, args.width, args.height, args.background)
        except Exception as exc:
            print(f"Failed on {url}\n{exc}", file=sys.stderr)
            return 3

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        ffmpeg_build_video(frames_dir, output_path, args.fps, args.crf, args.gop, args.codec)
    except Exception as exc:
        print(f"Failed to build video\n{exc}", file=sys.stderr)
        return 4

    print(f"Built: {output_path}")
    if args.keep_workdir:
        keep_file = output_path.with_suffix(".workdir.txt")
        keep_file.write_text(str(workdir), encoding="utf-8")
        workdir_obj.cleanup = lambda: None  # type: ignore[attr-defined]
        print(f"Kept workdir: {workdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
