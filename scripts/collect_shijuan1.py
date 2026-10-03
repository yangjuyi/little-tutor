"""Collect public exam-paper archives from shijuan1.com into private storage."""

from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import os
import re
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "outputs" / "private_sources" / "shijuan1"
PAPER_ROOT = ROOT / "data" / "private_questions" / "shijuan1"
MANIFEST_PATH = PAPER_ROOT / "manifest.json"
COLLECTOR_PID_PATH = SOURCE_ROOT / "collector.pid"
COLLECTOR_LOCK_PATH = SOURCE_ROOT / ".collector.lock"
BASE_URL = "https://www.shijuan1.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
THREAD_LOCAL = threading.local()

CATEGORIES = {
    "math_middle_exam": "/a/sjsxzk/",
    "math_high_exam": "/a/sjsxgk/",
    "physics_middle_exam": "/a/sjwlzk/",
    "physics_high_exam": "/a/sjwlgk/",
    "chemistry_middle_exam": "/a/sjhxzk/",
    "chemistry_high_exam": "/a/sjhxgk/",
}

REGIONS = (
    "全国",
    "北京",
    "天津",
    "上海",
    "重庆",
    "河北",
    "山西",
    "辽宁",
    "吉林",
    "黑龙江",
    "江苏",
    "浙江",
    "安徽",
    "福建",
    "江西",
    "山东",
    "河南",
    "湖北",
    "湖南",
    "广东",
    "广西",
    "海南",
    "四川",
    "贵州",
    "云南",
    "西藏",
    "陕西",
    "甘肃",
    "青海",
    "宁夏",
    "新疆",
    "内蒙古",
)


@dataclass
class PaperRecord:
    category: str
    article_id: str
    title: str
    article_url: str
    download_url: str
    local_archive: str
    extract_dir: str
    status: str
    year: int | None = None
    region: str = ""
    exam_type: str = ""
    published_date: str = ""
    document_type: str = ""
    error: str = ""


@dataclass(frozen=True)
class ArticleEntry:
    path: str
    title: str
    published_date: str
    document_type: str


def _decode(content: bytes) -> str:
    for encoding in ("gb18030", "utf-8"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _get(url: str, *, referer: str | None = None) -> requests.Response:
    session = getattr(THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=16)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        THREAD_LOCAL.session = session
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    response = session.get(url, headers=headers, timeout=(10, 60))
    response.raise_for_status()
    return response


def _load_manifest() -> dict[str, dict]:
    if not MANIFEST_PATH.exists():
        return {}
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    items = {}
    for item in payload.get("items") or []:
        title = item.get("title") or ""
        item.setdefault("year", _extract_year(title))
        item.setdefault("region", _extract_region(title))
        item.setdefault("exam_type", _extract_exam_type(title))
        item.setdefault("published_date", "")
        item.setdefault("document_type", "")
        items[item["article_id"]] = item
    return items


def _save_manifest(items: dict[str, dict]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = MANIFEST_PATH.with_name(
        f"{MANIFEST_PATH.name}.{os.getpid()}.tmp"
    )
    temp_path.write_text(
        json.dumps(
            {"items": sorted(items.values(), key=lambda i: i["article_id"])},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temp_path.replace(MANIFEST_PATH)


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _assert_not_launched_twice() -> None:
    if not COLLECTOR_PID_PATH.exists():
        return
    try:
        pid = int(COLLECTOR_PID_PATH.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return
    if pid != os.getpid() and _process_exists(pid):
        raise RuntimeError(
            f"采集器已在运行（pid={pid}），拒绝启动第二个实例"
        )
    try:
        COLLECTOR_PID_PATH.unlink()
    except OSError:
        pass


def _write_collector_pid() -> None:
    COLLECTOR_PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    COLLECTOR_PID_PATH.write_text(str(os.getpid()), encoding="ascii")


def _clear_collector_pid() -> None:
    try:
        pid = int(COLLECTOR_PID_PATH.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return
    if pid != os.getpid():
        return
    try:
        COLLECTOR_PID_PATH.unlink()
    except OSError:
        pass


@contextmanager
def _single_instance_lock():
    COLLECTOR_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with COLLECTOR_LOCK_PATH.open("a+", encoding="ascii") as handle:
        handle.seek(0)
        try:
            marker = handle.read(1)
        except OSError as exc:
            raise RuntimeError("采集器已在运行，拒绝启动第二个实例") from exc
        if not marker:
            handle.write("0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("采集器已在运行，拒绝启动第二个实例") from exc
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("采集器已在运行，拒绝启动第二个实例") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _extract_last_page(content: str) -> int:
    match = re.search(r"共\s*<strong>\s*(\d+)\s*</strong>\s*页", content)
    return int(match.group(1)) if match else 1


def _extract_page_id(content: str) -> str | None:
    match = re.search(r"list_(\d+)_2\.html", content)
    return match.group(1) if match else None


def _extract_article_entries(
    content: str,
    category_path: str,
) -> list[ArticleEntry]:
    pattern = re.compile(
        rf'<tr[^>]*>.*?href=["\']({re.escape(category_path)}\d+\.html)["\']'
        rf'[^>]*>(.*?)</a>.*?</tr>',
        re.IGNORECASE | re.S,
    )
    entries: list[ArticleEntry] = []
    seen: set[str] = set()
    for match in pattern.finditer(content):
        path = match.group(1)
        if path in seen:
            continue
        seen.add(path)
        row = match.group(0)
        title = html.unescape(
            re.sub(r"<[^>]+>", "", match.group(2)).strip()
        )
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.I | re.S)
        published_date = ""
        document_type = ""
        if len(cells) >= 6:
            document_type = html.unescape(
                re.sub(r"<[^>]+>", "", cells[1]).strip()
            )
            date_match = re.search(
                r"\d{4}-\d{2}-\d{2}",
                re.sub(r"<[^>]+>", " ", cells[-1]),
            )
            if date_match:
                published_date = date_match.group(0)
        entries.append(
            ArticleEntry(
                path=path,
                title=title,
                published_date=published_date,
                document_type=document_type,
            )
        )
    return sorted(entries, key=lambda item: item.path)


def _extract_year(title: str) -> int | None:
    years = re.findall(r"(?<!\d)(20\d{2})(?!\d)", title)
    if not years:
        return None
    return int(years[0])


def _extract_region(title: str) -> str:
    return next((region for region in REGIONS if region in title), "")


def _extract_exam_type(title: str) -> str:
    if "中考" in title:
        return "中考"
    if "高考" in title:
        return "高考"
    if "学业水平" in title or "学考" in title:
        return "学业水平"
    if "模拟" in title:
        return "模拟"
    return ""


def _year_allowed(
    title: str,
    *,
    min_year: int | None,
    max_year: int | None,
) -> bool:
    year = _extract_year(title)
    if year is None:
        return True
    if min_year is not None and year < min_year:
        return False
    if max_year is not None and year > max_year:
        return False
    return True


def _article_metadata(article_url: str) -> tuple[str, str]:
    response = _get(article_url)
    content = _decode(response.content)
    title_match = re.search(r"<title>(.*?)</title>", content, re.I | re.S)
    title = html.unescape(
        re.sub(r"<[^>]+>", "", title_match.group(1)).strip()
        if title_match else article_url.rsplit("/", 1)[-1]
    )
    download_match = re.search(
        r'href=["\']([^"\']+\.(?:rar|zip|docx?|pdf))["\'][^>]*>\s*本地下载',
        content,
        re.I,
    )
    if not download_match:
        raise ValueError("未找到本地下载链接")
    return title, urljoin(BASE_URL, html.unescape(download_match.group(1)))


def _download(url: str, target: Path, article_url: str) -> None:
    if target.exists() and target.stat().st_size > 0:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    response = _get(url, referer=article_url)
    target.write_bytes(response.content)


def _extract_archive(archive: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    if archive.suffix.lower() in (".rar", ".zip"):
        result = subprocess.run(
            ["tar", "-xf", str(archive), "-C", str(target_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"tar 解包失败：{result.stderr.strip() or result.stdout.strip()}"
            )
    else:
        (target_dir / archive.name).write_bytes(archive.read_bytes())


def _collect_category(
    category: str,
    category_path: str,
    manifest: dict[str, dict],
    *,
    max_articles: int | None,
    max_pages: int | None,
    delay: float,
    workers: int,
    min_year: int | None,
    max_year: int | None,
    index_only: bool,
) -> int:
    first_url = urljoin(BASE_URL, category_path)
    first = _get(first_url)
    first_content = _decode(first.content)
    last_page = _extract_last_page(first_content)
    page_id = _extract_page_id(first_content)
    collected = 0

    page_limit = last_page
    if max_pages is not None:
        page_limit = min(page_limit, max(0, max_pages))
    for page in range(1, page_limit + 1):
        if max_articles is not None and collected >= max_articles:
            break
        if page == 1:
            page_url = first_url
            content = first_content
        else:
            if not page_id:
                break
            page_url = urljoin(
                BASE_URL,
                f"{category_path}list_{page_id}_{page}.html",
            )
            content = _decode(_get(page_url).content)
        pending: list[ArticleEntry] = []
        for entry in _extract_article_entries(content, category_path):
            article_url = urljoin(BASE_URL, entry.path)
            article_id = entry.path.rsplit("/", 1)[-1].split(".", 1)[0]
            existing = manifest.get(article_id)
            if existing and existing.get("status") == "downloaded":
                continue
            if not _year_allowed(
                entry.title,
                min_year=min_year,
                max_year=max_year,
            ):
                if not existing:
                    manifest[article_id] = asdict(
                        PaperRecord(
                            category=category,
                            article_id=article_id,
                            title=entry.title,
                            article_url=article_url,
                            download_url="",
                            local_archive="",
                            extract_dir="",
                            status="year_filtered",
                            year=_extract_year(entry.title),
                            region=_extract_region(entry.title),
                            exam_type=_extract_exam_type(entry.title),
                            published_date=entry.published_date,
                            document_type=entry.document_type,
                        )
                    )
                continue
            if index_only:
                manifest[article_id] = asdict(
                    PaperRecord(
                        category=category,
                        article_id=article_id,
                        title=entry.title,
                        article_url=article_url,
                        download_url="",
                        local_archive="",
                        extract_dir="",
                        status="indexed",
                        year=_extract_year(entry.title),
                        region=_extract_region(entry.title),
                        exam_type=_extract_exam_type(entry.title),
                        published_date=entry.published_date,
                        document_type=entry.document_type,
                    )
                )
                collected += 1
                if max_articles is not None and collected >= max_articles:
                    break
                continue
            pending.append(entry)

        if index_only:
            _save_manifest(manifest)
            if delay:
                time.sleep(delay)
            continue

        attempted = 0
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, workers)
        ) as executor:
            future_to_entry = {}
            for entry in pending:
                if max_articles is not None and collected + len(
                    future_to_entry
                ) >= max_articles:
                    break
                future_to_entry[
                    executor.submit(
                        _collect_article,
                        category,
                        entry,
                    )
                ] = entry
                if delay:
                    time.sleep(delay)
            for future in concurrent.futures.as_completed(future_to_entry):
                entry = future_to_entry[future]
                record = future.result()
                manifest[record.article_id] = asdict(record)
                if record.status == "downloaded":
                    collected += 1
                attempted += 1
                if record.status != "downloaded" or attempted % 25 == 0:
                    print(
                        f"[{category}] page={page} attempted={attempted} "
                        f"downloaded={collected} "
                        f"{record.article_id} {record.status} "
                        f"{record.title}"
                    )
                if max_articles is not None and collected >= max_articles:
                    for pending_future in future_to_entry:
                        pending_future.cancel()
                    break
        _save_manifest(manifest)
    print(f"[{category}] done downloaded={collected}")
    return collected


def _collect_article(
    category: str,
    entry: ArticleEntry,
) -> PaperRecord:
    article_url = urljoin(BASE_URL, entry.path)
    article_id = entry.path.rsplit("/", 1)[-1].split(".", 1)[0]
    record = PaperRecord(
        category=category,
        article_id=article_id,
        title=entry.title,
        article_url=article_url,
        download_url="",
        local_archive="",
        extract_dir="",
        status="discovered",
        year=_extract_year(entry.title),
        region=_extract_region(entry.title),
        exam_type=_extract_exam_type(entry.title),
        published_date=entry.published_date,
        document_type=entry.document_type,
    )
    try:
        title, download_url = _article_metadata(article_url)
        archive_path = (
            SOURCE_ROOT
            / category
            / article_id
            / download_url.rsplit("/", 1)[-1]
        )
        extract_dir = PAPER_ROOT / category / article_id
        _download(download_url, archive_path, article_url)
        _extract_archive(archive_path, extract_dir)
        record.title = title or entry.title
        record.download_url = download_url
        record.local_archive = str(archive_path.relative_to(ROOT))
        record.extract_dir = str(extract_dir.relative_to(ROOT))
        record.status = "downloaded"
    except Exception as exc:
        record.status = "failed"
        record.error = str(exc)
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--category",
        action="append",
        choices=sorted(CATEGORIES),
        help="可重复指定；默认采集全部内置分类",
    )
    parser.add_argument("--max-articles", type=int, default=None)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--min-year", type=int, default=2016)
    parser.add_argument("--max-year", type=int, default=2026)
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="只记录列表页标题与来源，不访问文章页、不下载。",
    )
    args = parser.parse_args()

    try:
        with _single_instance_lock():
            _assert_not_launched_twice()
            _write_collector_pid()
            try:
                categories = args.category or list(CATEGORIES)
                manifest = _load_manifest()
                total = 0
                for category in categories:
                    total += _collect_category(
                        category,
                        CATEGORIES[category],
                        manifest,
                        max_articles=(
                            None
                            if args.max_articles is None
                            else max(0, args.max_articles - total)
                        ),
                        max_pages=args.max_pages,
                        delay=args.delay,
                        workers=args.workers,
                        min_year=args.min_year,
                        max_year=args.max_year,
                        index_only=args.index_only,
                    )
                    if (
                        args.max_articles is not None
                        and total >= args.max_articles
                    ):
                        break
                print(f"collected={total} manifest={MANIFEST_PATH}")
            finally:
                _clear_collector_pid()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
