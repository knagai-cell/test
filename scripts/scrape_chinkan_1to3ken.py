from __future__ import annotations

import asyncio
import csv
import json
import re
import ssl
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

BASE = "https://chinkan.jp"
TARGETS = {
    "11": "埼玉県",
    "12": "千葉県",
    "13": "東京都",
    "14": "神奈川県",
}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.5",
    "Cache-Control": "no-cache",
}
TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10, sock_read=20)
CONCURRENCY = 24
PER_HOST = 8
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"0\d{1,4}-\d{1,4}-\d{3,4}")
DETAIL_RE = re.compile(r"/shop/detail/\d+\.html", re.I)
INFO_RE = re.compile(r"/shop/info/\d+", re.I)
LABELS = {
    "事務所所在地", "TEL", "FAX", "MAIL", "宅建免許番号", "営業時間", "定休日",
    "交通", "代表者名", "ホームページ", "outline", "service", "staff", "sns",
}


@dataclass
class Lead:
    prefecture: str
    municipality: str
    company_name: str
    email: str
    phone: str
    address: str
    homepage: str
    source_url: str
    municipality_url: str
    services: str
    email_type: str
    researched_at: str


def clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_email(value: str) -> str:
    return value.strip().lower().replace("mailto:", "").split("?")[0]


def email_type(email: str) -> str:
    local = email.split("@", 1)[0].lower()
    if local in {"info", "contact", "office", "support", "mail", "webmaster", "customer", "eigyo", "sales"}:
        return "代表／部署アドレス"
    if any(token in local for token in ["shop", "store", "tenpo", "branch"]):
        return "店舗アドレス"
    if email.lower().endswith(("@gmail.com", "@yahoo.co.jp", "@outlook.com", "@hotmail.com", "@icloud.com")):
        return "公開フリーメール"
    return "担当者型／その他"


def text_lines(soup: BeautifulSoup) -> list[str]:
    return [clean(x) for x in soup.get_text("\n").splitlines() if clean(x)]


def next_value(lines: list[str], label: str) -> str:
    for i, line in enumerate(lines):
        if line == label or line.startswith(label + " "):
            for candidate in lines[i + 1 : i + 8]:
                if candidate not in LABELS and not candidate.lower().startswith("image"):
                    return candidate
    return ""


def infer_municipality(address: str, prefecture: str) -> str:
    value = address.replace(prefecture, "", 1).strip()
    patterns = [
        r"^(東京都)?(?P<x>[^0-9０-９]+?区)",
        r"^(?P<x>[^0-9０-９]+?市[^0-9０-９]*?区)",
        r"^(?P<x>[^0-9０-９]+?市)",
        r"^(?P<x>[^0-9０-９]+?郡[^0-9０-９]+?[町村])",
        r"^(?P<x>[^0-9０-９]+?[町村])",
    ]
    for pattern in patterns:
        m = re.search(pattern, value)
        if m:
            return clean(m.group("x"))
    return ""


def choose_homepage(soup: BeautifulSoup, source_url: str) -> str:
    source_host = (urlparse(source_url).hostname or "").lower()
    candidates: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(source_url, clean(a.get("href")))
        parsed = urlparse(href)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not host:
            continue
        if host == source_host or host.endswith(".chinkan.jp"):
            continue
        if any(x in host for x in ["facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com", "line.me"]):
            continue
        text = clean(a.get_text(" ", strip=True)).lower()
        score = 0
        if "ホームページ" in text or "website" in text or "公式" in text:
            score += 10
        if parsed.path in {"", "/"}:
            score += 2
        candidates.append((score, href))
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return candidates[0][1]


async def fetch(session: aiohttp.ClientSession, url: str, attempts: int = 4) -> tuple[int, str, str]:
    last_error = ""
    for attempt in range(attempts):
        try:
            async with session.get(url, allow_redirects=True) as response:
                raw = await response.read()
                encoding = response.charset or "utf-8"
                try:
                    body = raw.decode(encoding, errors="replace")
                except LookupError:
                    body = raw.decode("utf-8", errors="replace")
                if response.status in {403, 429, 500, 502, 503, 504} and attempt < attempts - 1:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                return response.status, str(response.url), body
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            last_error = type(exc).__name__
            if attempt < attempts - 1:
                await asyncio.sleep(1.5 * (attempt + 1))
    return 0, url, last_error


async def discover_info_urls(session: aiohttp.ClientSession) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for pref_code, pref_name in TARGETS.items():
        variants = [
            f"{BASE}/shop/town_search/{pref_code}/",
            f"{BASE}/shop/town_search/{pref_code}",
        ]
        body = ""
        final_url = variants[0]
        for url in variants:
            status, final_url, body = await fetch(session, url)
            if status == 200 and body:
                break
        if not body or "shop/info/" not in body:
            print(f"WARN: no municipality links for {pref_name}: status={status} url={final_url}", file=sys.stderr)
            continue
        soup = BeautifulSoup(body, "html.parser")
        for a in soup.find_all("a", href=True):
            href = urljoin(final_url, a.get("href"))
            if not INFO_RE.search(href):
                continue
            municipality = clean(a.get_text(" ", strip=True))
            municipality = re.sub(r"\s+\d+\s*$", "", municipality)
            found[href.rstrip("/")] = (pref_name, municipality)
        print(f"{pref_name}: municipality pages={sum(1 for v in found.values() if v[0] == pref_name)}")
    return found


async def discover_detail_urls(
    session: aiohttp.ClientSession,
    info_urls: dict[str, tuple[str, str]],
) -> dict[str, tuple[str, str, str]]:
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def one(info_url: str, meta: tuple[str, str]):
        async with semaphore:
            status, final_url, body = await fetch(session, info_url)
            urls: list[str] = []
            if status == 200 and body:
                soup = BeautifulSoup(body, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = urljoin(final_url, a.get("href"))
                    if DETAIL_RE.search(href):
                        urls.append(href.split("#", 1)[0])
            if not urls:
                print(f"WARN: no detail links: {info_url} status={status}", file=sys.stderr)
            return info_url, meta, sorted(set(urls))

    tasks = [asyncio.create_task(one(url, meta)) for url, meta in info_urls.items()]
    detail_map: dict[str, tuple[str, str, str]] = {}
    for future in asyncio.as_completed(tasks):
        info_url, (prefecture, municipality), detail_urls = await future
        for detail_url in detail_urls:
            detail_map[detail_url] = (prefecture, municipality, info_url)
    return detail_map


async def scrape_detail(
    session: aiohttp.ClientSession,
    detail_url: str,
    meta: tuple[str, str, str],
    semaphore: asyncio.Semaphore,
) -> Lead | None:
    async with semaphore:
        status, final_url, body = await fetch(session, detail_url)
    if status != 200 or not body:
        return None
    soup = BeautifulSoup(body, "html.parser")
    lines = text_lines(soup)

    heading = soup.find(["h1", "h2", "h3"])
    company = clean(heading.get_text(" ", strip=True) if heading else "")
    if not company:
        title = clean(soup.title.get_text(" ", strip=True) if soup.title else "")
        company = re.sub(r"\s*[-|｜].*$", "", title)
    if company in {"全宅管理", "会員店紹介"}:
        company = next_value(lines, "outline")

    emails = []
    for a in soup.select('a[href^="mailto:"]'):
        value = normalize_email(a.get("href", ""))
        if EMAIL_RE.fullmatch(value):
            emails.append(value)
    if not emails:
        for match in EMAIL_RE.findall(body):
            value = normalize_email(match)
            if EMAIL_RE.fullmatch(value):
                emails.append(value)
    emails = sorted(set(emails))
    if not emails:
        return None

    address = next_value(lines, "事務所所在地")
    phone = next_value(lines, "TEL")
    if not PHONE_RE.search(phone):
        m = PHONE_RE.search(" ".join(lines))
        phone = m.group(0) if m else ""
    homepage = choose_homepage(soup, final_url)
    prefecture, municipality, info_url = meta
    if not municipality and address:
        municipality = infer_municipality(address, prefecture)

    service_words = []
    for phrase in [
        "賃貸集金代行", "24時間管理体制", "サブリース（空室保証）", "相続対策相談",
        "司法書士・税理士等斡旋", "空き家管理", "学生向け物件取扱",
        "ペット可物件取扱い", "事務所・店舗取扱い", "駐車場取り扱い",
        "女性スタッフ", "外国語対応可",
    ]:
        if phrase in body:
            service_words.append(phrase)

    now = datetime.now(timezone.utc).isoformat()
    # One row per public email; the caller expands additional emails.
    return Lead(
        prefecture=prefecture,
        municipality=municipality,
        company_name=company,
        email=emails[0],
        phone=phone,
        address=address,
        homepage=homepage,
        source_url=final_url,
        municipality_url=info_url,
        services=" / ".join(service_words),
        email_type=email_type(emails[0]),
        researched_at=now,
    ), emails


async def main(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    ssl_context = ssl.create_default_context()
    connector = aiohttp.TCPConnector(
        limit=CONCURRENCY,
        limit_per_host=PER_HOST,
        ssl=ssl_context,
        ttl_dns_cache=600,
    )
    async with aiohttp.ClientSession(timeout=TIMEOUT, connector=connector, headers=HEADERS) as session:
        info_urls = await discover_info_urls(session)
        detail_map = await discover_detail_urls(session, info_urls)
        print(f"detail pages discovered={len(detail_map)}")
        semaphore = asyncio.Semaphore(CONCURRENCY)
        tasks = [
            asyncio.create_task(scrape_detail(session, url, meta, semaphore))
            for url, meta in detail_map.items()
        ]
        leads: list[dict[str, str]] = []
        failures = 0
        for future in asyncio.as_completed(tasks):
            result = await future
            if not result:
                failures += 1
                continue
            lead, emails = result
            for index, email in enumerate(emails):
                row = asdict(lead)
                row["email"] = email
                row["email_type"] = email_type(email)
                row["email_index"] = str(index + 1)
                leads.append(row)

    # Exact email de-duplication while preserving the first public source.
    deduped: dict[str, dict[str, str]] = {}
    for row in leads:
        key = normalize_email(row["email"])
        if key and key not in deduped:
            deduped[key] = row
    rows = sorted(deduped.values(), key=lambda r: (r["prefecture"], r["municipality"], r["company_name"], r["email"]))

    fieldnames = [
        "prefecture", "municipality", "company_name", "email", "email_type",
        "phone", "address", "homepage", "services", "source_url",
        "municipality_url", "email_index", "researched_at",
    ]
    with (output_dir / "chinkan_1to3ken_public_email_leads.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    (output_dir / "chinkan_1to3ken_public_email_leads.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = {
        "municipality_pages": len(info_urls),
        "detail_pages": len(detail_map),
        "detail_failures_or_no_email": failures,
        "public_email_rows": len(rows),
        "by_prefecture": dict(Counter(r["prefecture"] for r in rows)),
        "by_email_type": dict(Counter(r["email_type"] for r in rows)),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "output/chinkan_1to3ken")
    asyncio.run(main(target))
