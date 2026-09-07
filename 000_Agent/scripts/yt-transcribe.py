#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YouTube 批次逐字稿工具
=====================

兩段式管線：
  1. 快車道 —— 影片有 YouTube 字幕軌（手動或自動）就直接下載解析，一支約 2-5 秒。
  2. 慢車道 —— 沒有字幕軌的（例如會員影片、硬字幕影片）才下載 m4a 音訊，
     丟給 faster-whisper large-v3-turbo 轉錄。

產出：
  600_Projects/投資/逐字稿/YYYY-MM-DD_標題.md      （純逐字稿 + frontmatter）
  600_Projects/投資/逐字稿/_srt/<video_id>.srt      （帶時間軸，回頭對照用）

用法：
  python yt-transcribe.py <網址...> [選項]

範例：
  # 抓單支
  python yt-transcribe.py "https://www.youtube.com/watch?v=VtO9thgsubY"

  # 抓整個頻道最新 20 支
  python yt-transcribe.py "https://www.youtube.com/@宏爺講股/videos" --limit 20

  # 只走快車道，跳過需要 Whisper 的（先把有字幕的一次收乾淨）
  python yt-transcribe.py "https://www.youtube.com/@宏爺講股/videos" --skip-whisper

  # 看看有哪些要做，但不真的執行
  python yt-transcribe.py "https://www.youtube.com/@宏爺講股/videos" --dry-run
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- 路徑設定

VAULT = Path(r"C:\Users\user\Documents\GitHub\-")
OUT_DIR = VAULT / "600_Projects" / "投資" / "逐字稿"
DAILY_DIR = OUT_DIR / "每日分析"      # 時事與盤勢，標題帶日期，公開影片
MEMBER_DIR = OUT_DIR / "會員專題"      # 觀念教學與專題，會員限定，自帶流水號
SRT_DIR = OUT_DIR / "_srt"

# 會員專題的標題長這樣：「...  08/22/26 [海豚以上學員專屬(85)]」
# 括號裡的流水號是這個系列的期數，比日期更適合拿來排序。
MEMBER_TITLE_RE = re.compile(r"專屬|學員專屬|海豚以上|會員專屬")
MEMBER_SERIAL_RE = re.compile(r"專屬\s*[(（]\s*(\d+)\s*[)）]")

# yt-dlp 撞到會員牆時的錯誤訊息，中英文各一種說法
MEMBERS_ONLY_RE = re.compile(r"members[- ]only|available to this channel's members|僅供以下等級的頻道會員")

# cookie、狀態檔、暫存音訊全部放 repo 外面，確保不會被 Obsidian Git 推上 GitHub
CONF_DIR = Path(r"C:\Users\user\.config\yt-transcribe")
COOKIES = CONF_DIR / "cookies.txt"          # 主檔：你匯出的原始 cookie，腳本永不寫入
SESSION_COOKIES = CONF_DIR / "cache" / "session-cookies.txt"  # 每次執行用的拋棄式副本
CACHE_DIR = CONF_DIR / "cache"
AUDIO_DIR = CACHE_DIR / "audio"
STATE_FILE = CACHE_DIR / "state.json"

# yt-dlp 需要 Deno 來解 YouTube 的 JS 挑戰，winget 裝的位置不在預設 PATH 上
DENO_DIR = (
    Path(os.environ["LOCALAPPDATA"])
    / "Microsoft" / "WinGet" / "Packages"
    / "DenoLand.Deno_Microsoft.Winget.Source_8wekyb3d8bbwe"
)

# 字幕軌偏好順序：手動繁中 > 手動中文 > 自動繁中 > 自動中文
LANG_PREFERENCE = ["zh-TW", "zh-Hant", "zh-HK", "zh", "zh-Hans", "zh-CN"]

WHISPER_PROMPT = "以下是台股與美股、總體經濟、債券殖利率、聯準會政策的分析講解，使用繁體中文。"


# ---------------------------------------------------------------- 小工具

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def register_cuda_dlls():
    """ctranslate2 需要 CUDA 12 的 cuBLAS / cuDNN。

    這些 DLL 由 pip 套件 nvidia-cublas-cu12 / nvidia-cudnn-cu12 提供，
    但 Python 3.8 之後 Windows 不再從 PATH 搜尋擴充模組的相依 DLL，
    必須用 os.add_dll_directory 明確註冊，否則會噴
    "Library cublas64_12.dll is not found or cannot be loaded"。
    """
    import site

    roots = list(site.getsitepackages())
    try:
        roots.append(site.getusersitepackages())
    except Exception:  # noqa: BLE001
        pass

    found = []
    for root in roots:
        nvidia = Path(root) / "nvidia"
        if not nvidia.is_dir():
            continue
        for pkg in sorted(nvidia.iterdir()):
            bindir = pkg / "bin"
            if bindir.is_dir() and any(bindir.glob("*.dll")):
                found.append(str(bindir))

    for d in found:
        os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(d)
            except OSError:
                pass
    return found


def prepare_cookies():
    """把主 cookie 檔複製一份給 yt-dlp 用，主檔本身永不被寫入。

    yt-dlp 每次跑完都會把 cookie jar 寫回 --cookies 指定的檔案。YouTube
    在拒絕存取時會回傳清除性的 Set-Cookie，一旦寫回主檔，登入憑證就會
    被一次次侵蝕，最後整組 SID / SAPISID / LOGIN_INFO 全部消失，得重新
    匯出。所以這裡一律讓它去改拋棄式副本。
    """
    if not COOKIES.exists():
        return None
    SESSION_COOKIES.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(COOKIES, SESSION_COOKIES)
    return SESSION_COOKIES


def setup_env():
    """把 Deno 掛上 PATH、註冊 CUDA DLL、備妥 cookie 副本，並確保輸出是 UTF-8。"""
    if DENO_DIR.is_dir():
        os.environ["PATH"] = os.environ["PATH"] + os.pathsep + str(DENO_DIR)
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    register_cuda_dlls()
    for d in (OUT_DIR, DAILY_DIR, MEMBER_DIR, SRT_DIR, AUDIO_DIR):
        d.mkdir(parents=True, exist_ok=True)
    prepare_cookies()


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log("狀態檔讀不動，當作全新開始")
    return {}


def save_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE_FILE)


def safe_filename(name, limit=70):
    """把標題壓成檔名安全的字串。"""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "", name)
    name = re.sub(r"\s+", " ", name).strip().rstrip(".")
    return name[:limit].strip() or "untitled"


def fmt_duration(sec):
    if not sec:
        return "?"
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def srt_timestamp(sec):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ---------------------------------------------------------------- 簡轉繁

_converter = None

# 已經是繁體的字幕軌一律不轉換，原文照抄。
# 只有 Whisper 輸出（必為簡體）才轉，且用 s2tw 而非 s2twp——
# s2twp 會把「數據」改成「資料」、「設備」改成「裝置」，那是竄改原意，不是轉換字體。
TRADITIONAL_LANGS = {"zh-TW", "zh-Hant", "zh-HK"}

# s2tw 會把「台」一律變「臺」，但台灣財經圈慣用「台」，這裡改回來。
_FIXUPS = [
    ("臺積電", "台積電"), ("臺灣", "台灣"), ("臺股", "台股"), ("臺幣", "台幣"),
    ("臺北", "台北"), ("臺中", "台中"), ("臺南", "台南"), ("臺塑", "台塑"),
    ("臺電", "台電"), ("臺達電", "台達電"), ("臺泥", "台泥"), ("臺化", "台化"),
    ("在臺", "在台"), ("來臺", "來台"), ("赴臺", "赴台"), ("全臺", "全台"),
]


def to_traditional(text, convert=True):
    """簡轉繁。convert=False 代表來源已是繁體，直接原樣回傳。"""
    if not convert or not text:
        return text
    global _converter
    if _converter is None:
        try:
            from opencc import OpenCC
            _converter = OpenCC("s2tw")
        except Exception as e:  # noqa: BLE001
            log(f"opencc 載入失敗，跳過簡轉繁：{e}")
            _converter = False
    if not _converter:
        return text
    try:
        text = _converter.convert(text)
    except Exception:  # noqa: BLE001
        return text
    for wrong, right in _FIXUPS:
        text = text.replace(wrong, right)
    return text


# ---------------------------------------------------------------- yt-dlp

def make_ydl(extra=None):
    from yt_dlp import YoutubeDL

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "extractor_args": {"youtube": {"lang": ["zh-TW"]}},
        "retries": 5,
        "socket_timeout": 30,
    }
    if SESSION_COOKIES.exists():
        opts["cookiefile"] = str(SESSION_COOKIES)
    elif COOKIES.exists():
        opts["cookiefile"] = str(prepare_cookies())
    if extra:
        opts.update(extra)
    return YoutubeDL(opts)


def enumerate_targets(urls, limit=None):
    """把頻道／播放清單網址攤平成影片清單；單支影片網址原樣通過。"""
    targets, seen = [], set()
    with make_ydl({"extract_flat": "in_playlist"}) as ydl:
        for url in urls:
            log(f"清點：{url}")
            try:
                info = ydl.extract_info(url, download=False)
            except Exception as e:  # noqa: BLE001
                log(f"  清點失敗：{e}")
                continue

            entries = info.get("entries")
            if entries is None:
                entries = [info]

            def walk(items):
                for it in items:
                    if it is None:
                        continue
                    if it.get("_type") == "playlist" and it.get("entries"):
                        walk(it["entries"])
                        continue
                    vid = it.get("id")
                    if vid and vid not in seen:
                        seen.add(vid)
                        targets.append({
                            "id": vid,
                            "title": it.get("title") or vid,
                            "duration": it.get("duration"),
                        })

            walk(entries)

    if limit:
        targets = targets[:limit]
    return targets


# ---------------------------------------------------------------- 字幕解析

def pick_subtitle_track(info):
    """依偏好挑一條中文字幕軌，回傳 (url, 語言, 來源)；沒有就 None。"""
    for source, key in (("手動字幕", "subtitles"), ("自動字幕", "automatic_captions")):
        tracks = info.get(key) or {}
        for lang in LANG_PREFERENCE:
            fmts = tracks.get(lang)
            if not fmts:
                continue
            # json3 最好解析；退而求其次用 vtt
            for want in ("json3", "srv3", "vtt"):
                for f in fmts:
                    if f.get("ext") == want and f.get("url"):
                        return f["url"], lang, source, want
    return None


def parse_json3(raw):
    """解析 YouTube 的 json3 字幕，回傳 [(起, 訖, 文字), ...]。"""
    data = json.loads(raw)
    lines = []
    for ev in data.get("events", []):
        # aAppend 是自動字幕的滾動殘影，內容跟前一句重複，直接丟掉
        if ev.get("aAppend"):
            continue
        segs = ev.get("segs") or []
        text = "".join(s.get("utf8", "") for s in segs)
        text = text.replace("\n", " ").strip()
        if not text:
            continue
        start = ev.get("tStartMs", 0) / 1000
        dur = ev.get("dDurationMs", 0) / 1000
        lines.append((start, start + dur, text))
    return lines


def parse_vtt(raw):
    """最陽春的 WebVTT 解析，只在拿不到 json3 時當備胎。"""
    lines, cur_start, cur_end, buf = [], None, None, []
    ts = re.compile(
        r"(\d+):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d+):(\d{2}):(\d{2})[.,](\d{3})"
    )

    def flush():
        if cur_start is not None and buf:
            text = " ".join(buf).strip()
            if text:
                lines.append((cur_start, cur_end, text))

    for line in raw.splitlines():
        line = line.strip()
        m = ts.search(line)
        if m:
            flush()
            buf = []
            h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, m.groups())
            cur_start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
            cur_end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000
        elif line and not line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            buf.append(re.sub(r"<[^>]+>", "", line))
    flush()

    # 自動字幕的滾動重複：後一句常整段包含前一句
    deduped = []
    for item in lines:
        if deduped and item[2] == deduped[-1][2]:
            continue
        deduped.append(item)
    return deduped


def fetch_subtitles(info):
    """回傳 (lines, 描述字串, 是否需簡轉繁)；沒有字幕軌回傳 (None, None, False)。"""
    picked = pick_subtitle_track(info)
    if not picked:
        return None, None, False
    url, lang, source, ext = picked
    with make_ydl() as ydl:
        raw = ydl.urlopen(url).read().decode("utf-8", errors="replace")
    lines = parse_json3(raw) if ext in ("json3", "srv3") else parse_vtt(raw)
    if not lines:
        return None, None, False
    # 繁體軌原文照抄，不做任何字體轉換
    return lines, f"youtube-{source}({lang})", lang not in TRADITIONAL_LANGS


# ---------------------------------------------------------------- Whisper

_whisper = None


def get_whisper(model_name, device, compute_type):
    global _whisper
    if _whisper is None:
        from faster_whisper import BatchedInferencePipeline, WhisperModel

        log(f"載入 Whisper 模型 {model_name}（{device}/{compute_type}），首次會下載權重…")
        try:
            base = WhisperModel(model_name, device=device, compute_type=compute_type)
        except Exception as e:  # noqa: BLE001
            log(f"  {device} 起不來（{e}），退回 CPU")
            base = WhisperModel(model_name, device="cpu", compute_type="int8")
        _whisper = BatchedInferencePipeline(model=base)
        log("模型就緒")
    return _whisper


def download_audio(video_id):
    """只抓 m4a 音訊軌（format 140），不需要 ffmpeg 轉檔。"""
    target = AUDIO_DIR / f"{video_id}.m4a"
    if target.exists() and target.stat().st_size > 0:
        return target
    opts = {
        "format": "140/bestaudio[ext=m4a]/bestaudio",
        "outtmpl": str(AUDIO_DIR / "%(id)s.%(ext)s"),
        "overwrites": True,
    }
    with make_ydl(opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    for cand in AUDIO_DIR.glob(f"{video_id}.*"):
        if cand.suffix != ".part":
            return cand
    raise RuntimeError("音訊下載後找不到檔案")


def whisper_transcribe(audio_path, args):
    global _whisper

    def run(device, compute_type):
        model = get_whisper(args.model, device, compute_type)
        segments, _ = model.transcribe(
            str(audio_path),
            language="zh",
            batch_size=args.batch_size,
            vad_filter=True,
            initial_prompt=WHISPER_PROMPT,
            condition_on_previous_text=False,
        )
        # segments 是 generator，必須在這裡實體化，錯誤才會在 try 內被接住
        return [(x.start, x.end, x.text.strip()) for x in segments if x.text.strip()]

    try:
        return run(args.device, args.compute_type)
    except Exception as e:  # noqa: BLE001
        if args.device == "cpu":
            raise
        log(f"  GPU 轉錄失敗（{e}）")
        log("  改用 CPU 重試——會慢很多，但至少跑得完")
        _whisper = None
        args.device, args.compute_type = "cpu", "int8"
        return run("cpu", "int8")


# ---------------------------------------------------------------- 輸出

PUNCT_END = ("。", "！", "？", "，", "、", "；", "：", ".", "!", "?", ",")


def build_paragraphs(lines, max_chars=180):
    """把零碎字幕句子併成好讀的段落。

    YouTube 自動字幕與 Whisper 的中文輸出通常都沒有標點。這裡刻意不替
    講者補標點——那等於捏造他的斷句——改用空格分隔原本的語句群，讓段落
    讀得下去又不更動內容。來源本身就有標點的則不再加空格。
    """
    paras, buf = [], ""
    for _, _, text in lines:
        if not buf:
            buf = text
            continue
        sep = "" if buf.endswith(PUNCT_END) else " "
        buf = f"{buf}{sep}{text}"
        if len(buf) >= max_chars:
            paras.append(buf)
            buf = ""
    if buf:
        paras.append(buf)
    return "\n\n".join(paras)


def write_srt(lines, video_id):
    out = []
    for i, (start, end, text) in enumerate(lines, 1):
        out.append(f"{i}\n{srt_timestamp(start)} --> {srt_timestamp(end)}\n{text}\n")
    (SRT_DIR / f"{video_id}.srt").write_text("\n".join(out), encoding="utf-8")


def classify(info):
    """判斷是「會員專題」還是「每日分析」。

    優先看 yt-dlp 的 availability 欄位（subscriber_only 就是會員限定），
    這是 YouTube 給的權威答案。但那個欄位只有在真的取得影片資料時才有，
    所以再用標題規則兜底——會員專題的標題一定帶「[海豚以上學員專屬(NN)]」，
    光靠清單階段的標題就分得出來，不需要會員權限。
    """
    availability = (info.get("availability") or "").lower()
    title = info.get("title") or ""

    is_member = availability == "subscriber_only" or bool(MEMBER_TITLE_RE.search(title))

    serial = None
    m = MEMBER_SERIAL_RE.search(title)
    if m:
        serial = int(m.group(1))

    return ("會員專題" if is_member else "每日分析"), serial


def write_markdown(info, lines, method, convert=True):
    vid = info["id"]
    title = info.get("title") or vid
    upload = info.get("upload_date")
    date_str = (
        f"{upload[:4]}-{upload[4:6]}-{upload[6:8]}" if upload and len(upload) == 8
        else datetime.now().strftime("%Y-%m-%d")
    )

    body = to_traditional(build_paragraphs(lines), convert)
    title_tw = to_traditional(title, convert)
    category, serial = classify(info)
    is_member = category == "會員專題"

    fm = [
        "---",
        f'title: "{title_tw.replace(chr(34), chr(39))}"',
        f"source: https://www.youtube.com/watch?v={vid}",
        f'channel: "{to_traditional(info.get("uploader") or "", convert).replace(chr(34), chr(39))}"',
        f"video_id: {vid}",
        f"category: {category}",
        f"access: {'會員限定' if is_member else '公開'}",
    ]
    if serial is not None:
        fm.append(f"series_no: {serial}")
    fm += [
        f"upload_date: {date_str}",
        f"duration: {fmt_duration(info.get('duration'))}",
        f"method: {method}",
        f"captured: {datetime.now():%Y-%m-%d}",
        "tags:",
        "  - 投資",
        "  - 逐字稿",
        f"  - {'會員專題' if is_member else '每日分析'}",
        "---",
        "",
        f"# {title_tw}",
        "",
        f"> [!info] 來源｜[YouTube 原片](https://www.youtube.com/watch?v={vid})"
        f"｜{fmt_duration(info.get('duration'))}｜{category}"
        + (f"　第 {serial} 期" if serial is not None else "")
        + f"｜取得方式：{method}",
        "",
        body,
        "",
    ]

    # 會員專題自帶流水號，用編號開頭排序比日期直覺；每日分析則維持日期開頭
    if is_member and serial is not None:
        name = f"{serial:03d}_{date_str}_{safe_filename(title_tw)}.md"
    else:
        name = f"{date_str}_{safe_filename(title_tw)}.md"

    path = (MEMBER_DIR if is_member else DAILY_DIR) / name
    path.write_text("\n".join(fm), encoding="utf-8")
    return path


# ---------------------------------------------------------------- 主流程

def probe(target):
    """抓單支影片的完整 info，並判斷走哪條車道。"""
    vid = target["id"]
    with make_ydl({"skip_download": True}) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
    lines, method, convert = fetch_subtitles(info)
    return info, lines, method, convert


def main():
    p = argparse.ArgumentParser(
        description="YouTube 批次逐字稿：有字幕就抓字幕，沒字幕才跑 Whisper"
    )
    p.add_argument("urls", nargs="+", help="影片／播放清單／頻道網址")
    p.add_argument("--limit", type=int, help="只處理前 N 支")
    p.add_argument("--force", action="store_true", help="忽略已完成紀錄，全部重做")
    p.add_argument("--dry-run", action="store_true", help="只列出待處理清單，不執行")
    p.add_argument("--skip-whisper", action="store_true",
                   help="只走快車道；沒字幕的記錄下來但不轉錄")
    p.add_argument("--workers", type=int, default=4, help="快車道並行數（預設 4）")
    p.add_argument("--model", default="large-v3-turbo", help="Whisper 模型")
    p.add_argument("--device", default="cuda", help="cuda 或 cpu")
    p.add_argument("--compute-type", default="int8_float16",
                   help="1660 Ti 沒有 tensor core，int8_float16 最快")
    p.add_argument("--batch-size", type=int, default=8, help="Whisper 批次大小")
    args = p.parse_args()

    setup_env()
    state = {} if args.force else load_state()

    targets = enumerate_targets(args.urls, args.limit)
    if not targets:
        log("沒有找到任何影片")
        return 1

    todo = [t for t in targets if t["id"] not in state]
    log(f"共 {len(targets)} 支，已完成 {len(targets) - len(todo)} 支，待處理 {len(todo)} 支")

    if args.dry_run:
        for t in todo[:40]:
            log(f"  待辦 {t['id']}  {fmt_duration(t.get('duration')):>7}  {t['title'][:50]}")
        if len(todo) > 40:
            log(f"  …另有 {len(todo) - 40} 支")
        return 0

    if not todo:
        log("沒有新的東西要做")
        return 0

    # ---- 第一階段：並行探測 + 快車道直接寫檔
    whisper_queue = []
    blocked = []          # 被會員牆擋下的，不是錯誤，是缺權限
    fast_done = 0
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(probe, t): t for t in todo}
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                info, lines, method, convert = fut.result()
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if MEMBERS_ONLY_RE.search(msg):
                    blocked.append(t)
                else:
                    log(f"✗ {t['id']} 探測失敗：{e}")
                continue

            if lines:
                try:
                    path = write_markdown(info, lines, method, convert)
                    write_srt(lines, info["id"])
                    state[info["id"]] = {
                        "method": method,
                        "file": path.name,
                        "done_at": datetime.now().isoformat(timespec="seconds"),
                    }
                    fast_done += 1
                    log(f"✓ 字幕 {path.name}")
                except Exception as e:  # noqa: BLE001
                    log(f"✗ {t['id']} 寫檔失敗：{e}")
            else:
                whisper_queue.append(info)

            if fast_done % 20 == 0 and fast_done:
                save_state(state)

    save_state(state)
    log(f"快車道完成 {fast_done} 支，耗時 {time.time() - t0:.0f} 秒；"
        f"需要 Whisper 的有 {len(whisper_queue)} 支")

    if blocked:
        log("")
        log(f"⚠ 有 {len(blocked)} 支被會員牆擋下，未處理。")
        log("  cookie 沒有帶到會員身分。可能原因：")
        log("  1) 匯出時 Chrome 停在非會員的那個 Google 帳號")
        log("  2) cookie 已過期或被登出")
        log(f"  重新匯出後覆蓋 {COOKIES} 再跑一次即可（已完成的不會重做）")
        for t in blocked[:10]:
            log(f"    {t['id']}  {t['title'][:50]}")
        if len(blocked) > 10:
            log(f"    …另有 {len(blocked) - 10} 支")
        log("")

    if args.skip_whisper or not whisper_queue:
        if whisper_queue:
            log("（--skip-whisper 已指定，以下未處理）")
            for info in whisper_queue:
                log(f"  待轉錄 {info['id']}  {info.get('title', '')[:50]}")
        return 0

    # ---- 第二階段：GPU 逐支轉錄
    total_audio = sum(i.get("duration") or 0 for i in whisper_queue)
    log(f"開始轉錄，音訊總長 {fmt_duration(total_audio)}")

    for n, info in enumerate(whisper_queue, 1):
        vid = info["id"]
        title = info.get("title", vid)[:40]
        log(f"[{n}/{len(whisper_queue)}] {vid} {title}")
        started = time.time()
        audio = None
        try:
            audio = download_audio(vid)
            lines = whisper_transcribe(audio, args)
            if not lines:
                log("  ✗ 轉錄結果是空的，跳過")
                continue
            method = f"whisper-{args.model}"
            path = write_markdown(info, lines, method, convert=True)
            write_srt(lines, vid)
            state[vid] = {
                "method": method,
                "file": path.name,
                "done_at": datetime.now().isoformat(timespec="seconds"),
            }
            save_state(state)
            spent = time.time() - started
            speed = (info.get("duration") or 0) / spent if spent else 0
            log(f"  ✓ {path.name}（{spent:.0f} 秒，{speed:.1f}x 實時）")
        except KeyboardInterrupt:
            log("中斷，已完成的部分都存好了，直接重跑會接續")
            save_state(state)
            return 130
        except Exception as e:  # noqa: BLE001
            log(f"  ✗ 失敗：{e}")
        finally:
            # 音訊是暫存，轉完就刪，不佔硬碟
            if audio and audio.exists():
                try:
                    audio.unlink()
                except OSError:
                    pass

    save_state(state)
    log("全部完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
