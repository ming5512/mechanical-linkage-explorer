from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request, send_from_directory
from PIL import Image


BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache"
INDEX_FILE = CACHE_DIR / "index.json"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)
SEARCH_LIMIT = 15
REQUEST_TIMEOUT = 12

app = Flask(__name__)
app.logger.setLevel(logging.INFO)


def ensure_cache() -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    if not INDEX_FILE.exists():
        INDEX_FILE.write_text("{}", encoding="utf-8")


def load_index() -> dict[str, dict[str, Any]]:
    ensure_cache()
    return json.loads(INDEX_FILE.read_text(encoding="utf-8"))


def save_index(index: dict[str, dict[str, Any]]) -> None:
    INDEX_FILE.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def normalize_query(raw_query: str) -> str:
    query = " ".join(raw_query.strip().split())
    return query


def cache_key(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]


def is_cache_entry_usable(entry: dict[str, Any]) -> bool:
    filename = entry.get("filename")
    if not filename:
        return False
    return (CACHE_DIR / filename).exists()


def extract_bing_candidates(query: str) -> list[str]:
    params = {"q": f"{query} gif 动图 机械原理", "form": "HDRSC3"}
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"}
    response = requests.get(
        "https://www.bing.com/images/search",
        params=params,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    document = response.text
    urls: list[str] = []
    seen: set[str] = set()

    soup = BeautifulSoup(document, "html.parser")
    for anchor in soup.select("a.iusc[m]"):
        payload = anchor.get("m")
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        candidate = data.get("murl")
        if candidate and candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)

    for raw_match in re.findall(r'murl(?:&quot;|"):(?:&quot;|")(.*?)(?:&quot;|")', document):
        candidate = html.unescape(raw_match).replace("\\/", "/")
        if candidate and candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)

    return urls


def file_looks_like_gif(content: bytes) -> bool:
    return content.startswith((b"GIF87a", b"GIF89a"))


def is_animated_gif(file_path: Path) -> bool:
    with Image.open(file_path) as image:
        return getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) > 1


def choose_extension(url: str, content_type: str) -> str:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix == ".gif":
        return ".gif"
    if "gif" in content_type.lower():
        return ".gif"
    return suffix or ".bin"


def download_animation(query: str, candidates: list[str]) -> dict[str, str] | None:
    headers = {"User-Agent": USER_AGENT, "Referer": "https://www.bing.com/"}
    key = cache_key(query)

    for index, url in enumerate(candidates[:SEARCH_LIMIT], start=1):
        try:
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            app.logger.info("Skip candidate %s for '%s': %s", index, query, exc)
            continue

        content_type = response.headers.get("Content-Type", "")
        if ".gif" not in url.lower() and "gif" not in content_type.lower():
            continue

        extension = choose_extension(url, content_type)
        filename = f"{key}{extension}"
        file_path = CACHE_DIR / filename
        file_path.write_bytes(response.content)

        if not file_looks_like_gif(response.content):
            file_path.unlink(missing_ok=True)
            continue

        try:
            if not is_animated_gif(file_path):
                file_path.unlink(missing_ok=True)
                continue
        except OSError as exc:
            app.logger.info("Invalid image for '%s': %s", query, exc)
            file_path.unlink(missing_ok=True)
            continue

        return {"filename": filename, "source_url": url}

    return None


@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.route("/cache/<path:filename>")
def serve_cache(filename: str):
    return send_from_directory(CACHE_DIR, filename)


@app.post("/api/search")
def search_animation():
    data = request.get_json(silent=True) or {}
    query = normalize_query(str(data.get("query", "")))

    if not query:
        return jsonify({"message": "请输入机械结构名称。"}), 400

    index = load_index()
    entry = index.get(query)
    if entry and is_cache_entry_usable(entry):
        return jsonify(
            {
                "query": query,
                "cached": True,
                "mediaPath": f"/cache/{entry['filename']}",
                "sourceUrl": entry["source_url"],
            }
        )

    try:
        candidates = extract_bing_candidates(query)
    except requests.RequestException as exc:
        app.logger.error("Search failed for '%s': %s", query, exc)
        return jsonify({"message": "搜索远程资源失败，请稍后重试。"}), 502

    if not candidates:
        return jsonify({"message": "没有找到可用候选资源。"}), 404

    result = download_animation(query, candidates)
    if result is None:
        return jsonify({"message": "找到了候选资源，但没有筛到可用 GIF 动图。"}), 404

    index[query] = result
    save_index(index)

    return jsonify(
        {
            "query": query,
            "cached": False,
            "mediaPath": f"/cache/{result['filename']}",
            "sourceUrl": result["source_url"],
        }
    )


if __name__ == "__main__":
    ensure_cache()
    app.run(debug=True, host="127.0.0.1", port=5000)
