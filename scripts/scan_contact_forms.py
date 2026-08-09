from __future__ import annotations

import asyncio
import csv
import html
import re
import ssl
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import aiohttp
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (compatible; PPconnectContactFormResearch/1.0; "
    "+https://ppconnect.co.jp/)"
)
TOTAL_CONCURRENCY = 70
PER_HOST = 2
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=12, connect=6, sock_read=8)
MAX_BODY_BYTES = 2_000_000

CONTACT_TERMS = [
    "お問い合わせ", "お問合せ", "お問い合せ", "問い合わせ", "問合せ", "問い合せ",
    "contact", "inquiry", "ご相談", "無料相談", "相談する", "来店予約", "内見予約",
    "見学予約", "査定依頼", "売却査定", "無料査定", "物件リクエスト", "物件問い合わせ",
    "資料請求", "入居相談", "空室相談", "オーナー相談", "フォーム",
]
URL_HINTS = [
    "/contact", "/inquiry", "/form", "/request", "/reserve", "/reservation",
    "/consult", "/satei", "/assessment", "/otoiawase", "/mail", "contact.php",
    "inquiry.php", "form.php",
]
EXTERNAL_FORM_HOSTS = [
    "docs.google.com", "forms.gle", "form.run", "form-mailer.jp", "ssl.form-mailer.jp",
    "hubspot.com", "hsforms.com", "salesforce.com", "pardot.com", "kintoneapp.com",
    "select-type.com", "coubic.com", "reserva.be", "airreserve.net", "line.me",
]
NON_CONTACT_PATTERNS = [
    "login", "signin", "search", "site-search", "newsletter", "member", "mypage",
    "recruit", "entry", "apply", "応募", "採用",
]
COMMON_PATHS = ["/contact/", "/contact", "/inquiry/", "/form/"]
SPACE_RE = re.compile(r"\s+")


@dataclass
class Result:
    row_no: str
    company_name: str
    prefecture: str
    municipality: str
    official_site: str
    source_url: str
    public_email: str
    form_status: str
    contact_form_url: str
    form_type: str
    external_form: str
    evidence: str
    homepage_status: str
    resolved_homepage: str
    candidate_count: int
    scanned_at: str


def clean_text(value: str | None) -> str:
    return SPACE_RE.sub(" ", html.unescape(value or "")).strip()


def normalize_url(raw: str | None) -> str:
    value = clean_text(raw)
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value.lstrip("/")
    try:
        p = urlparse(value)
        if not p.hostname:
            return ""
        scheme = p.scheme.lower() if p.scheme.lower() in {"http", "https"} else "https"
        return urlunparse((scheme, p.netloc, p.path or "/", "", "", ""))
    except Exception:
        return ""


def root_url(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, "/", "", "", ""))


def same_site(a: str, b: str) -> bool:
    try:
        ah = (urlparse(a).hostname or "").lower().removeprefix("www.")
        bh = (urlparse(b).hostname or "").lower().removeprefix("www.")
        return ah == bh or ah.endswith("." + bh) or bh.endswith("." + ah)
    except Exception:
        return False


def is_external_form_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in EXTERNAL_FORM_HOSTS)


def contact_score(text: str, href: str) -> int:
    combined = (text + " " + href).lower()
    score = 0
    for term in CONTACT_TERMS:
        if term.lower() in combined:
            score += 5
    for hint in URL_HINTS:
        if hint.lower() in href.lower():
            score += 4
    for bad in NON_CONTACT_PATTERNS:
        if bad.lower() in combined:
            score -= 6
    if href.lower().startswith(("mailto:", "tel:", "javascript:")):
        return -100
    if href.startswith("#"):
        score -= 4
    if is_external_form_host(href):
        score += 5
    return score


def candidate_links(page_url: str, body: str) -> list[tuple[int, str, str]]:
    soup = BeautifulSoup(body, "html.parser")
    candidates: dict[str, tuple[int, str]] = {}
    for tag in soup.find_all(["a", "button"]):
        href = clean_text(tag.get("href") or tag.get("data-href") or tag.get("data-url"))
        text = clean_text(tag.get_text(" ", strip=True) + " " + (tag.get("aria-label") or "") + " " + (tag.get("title") or ""))
        if not href:
            continue
        absolute = urljoin(page_url, href)
        if urlparse(absolute).scheme not in {"http", "https"}:
            continue
        score = contact_score(text, absolute)
        if score < 4:
            continue
        old = candidates.get(absolute)
        if old is None or score > old[0]:
            candidates[absolute] = (score, text[:180])
    return sorted([(s, u, t) for u, (s, t) in candidates.items()], reverse=True)[:8]


def detect_form(page_url: str, body: str, context: str = "") -> tuple[bool, str, str]:
    soup = BeautifulSoup(body, "html.parser")
    title = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
    page_context = f"{page_url} {title} {context}".lower()

    for tag in soup.find_all(["iframe", "script", "a"]):
        target = clean_text(tag.get("src") or tag.get("href"))
        if target:
            target = urljoin(page_url, target)
            if is_external_form_host(target):
                return True, "外部フォーム", f"外部フォーム埋め込み/リンク: {target[:220]}"

    for form in soup.find_all("form"):
        form_text = clean_text(form.get_text(" ", strip=True))
        action = clean_text(form.get("action"))
        combined = f"{page_context} {form_text} {action}".lower()
        fields = form.find_all(["input", "textarea", "select"])
        textareas = form.find_all("textarea")
        names = " ".join(clean_text(x.get("name") or x.get("id") or x.get("placeholder") or x.get("type")) for x in fields).lower()
        contact_signals = sum(term.lower() in combined for term in CONTACT_TERMS)
        field_signals = sum(k in names for k in ["name", "email", "mail", "tel", "phone", "message", "comment", "内容", "氏名", "電話"])
        bad_signals = sum(k in combined for k in NON_CONTACT_PATTERNS)
        if (contact_signals >= 1 and len(fields) >= 2) or (textareas and field_signals >= 1) or (field_signals >= 3 and bad_signals == 0):
            kind = "問い合わせフォーム"
            if any(k in combined for k in ["査定", "satei", "assessment"]):
                kind = "査定フォーム"
            elif any(k in combined for k in ["来店予約", "内見予約", "reserve", "reservation"]):
                kind = "予約フォーム"
            elif any(k in combined for k in ["物件リクエスト", "物件問い合わせ", "request"]):
                kind = "物件問い合わせフォーム"
            return True, kind, f"HTML form検出（入力欄{len(fields)}件、title={title[:100]}）"

    visible = clean_text(soup.get_text(" ", strip=True)).lower()
    if any(term.lower() in page_context for term in CONTACT_TERMS) and any(k in visible for k in ["確認画面", "送信する", "入力内容", "必須項目", "プライバシーポリシーに同意"]):
        return True, "問い合わせフォーム（JS）", f"問い合わせページ上の送信・入力文言を検出（title={title[:100]}）"
    return False, "", ""


async def fetch(session: aiohttp.ClientSession, url: str) -> tuple[int, str, str, str]:
    try:
        async with session.get(url, allow_redirects=True) as response:
            content_type = (response.headers.get("content-type") or "").lower()
            if "text/html" not in content_type and "application/xhtml" not in content_type and content_type:
                return response.status, str(response.url), "", f"non-html:{content_type[:60]}"
            raw = await response.content.read(MAX_BODY_BYTES)
            encoding = response.charset or "utf-8"
            try:
                text = raw.decode(encoding, errors="replace")
            except LookupError:
                text = raw.decode("utf-8", errors="replace")
            return response.status, str(response.url), text, ""
    except asyncio.TimeoutError:
        return 0, url, "", "timeout"
    except aiohttp.ClientConnectorCertificateError:
        return 0, url, "", "ssl-error"
    except aiohttp.ClientError as exc:
        return 0, url, "", type(exc).__name__
    except Exception as exc:
        return 0, url, "", type(exc).__name__


async def scan_one(session: aiohttp.ClientSession, row: dict[str, str]) -> Result:
    scanned_at = datetime.now(timezone.utc).isoformat()
    site = normalize_url(row.get("official_site"))
    if not site:
        return Result(row.get("row_no", ""), row.get("company_name", ""), row.get("prefecture", ""), row.get("municipality", ""), "", row.get("source_url", ""), row.get("public_email", ""), "公式サイトなし", "", "", "", "公式サイトURLが未登録", "", "", 0, scanned_at)

    status, final_url, body, error = await fetch(session, site)
    if status == 0 and site.startswith("https://"):
        fallback = "http://" + site[len("https://"):]
        status, final_url, body, error = await fetch(session, fallback)
    if not body:
        return Result(row.get("row_no", ""), row.get("company_name", ""), row.get("prefecture", ""), row.get("municipality", ""), site, row.get("source_url", ""), row.get("public_email", ""), "アクセス不可", "", "", "", error or f"HTTP {status}", str(status or ""), final_url, 0, scanned_at)

    found, form_type, evidence = detect_form(final_url, body, "homepage")
    if found:
        return Result(row.get("row_no", ""), row.get("company_name", ""), row.get("prefecture", ""), row.get("municipality", ""), site, row.get("source_url", ""), row.get("public_email", ""), "あり", final_url, form_type, "いいえ", evidence, str(status), final_url, 0, scanned_at)

    links = candidate_links(final_url, body)
    checked: set[str] = set()
    for score, link, text in links:
        if link in checked:
            continue
        checked.add(link)
        if is_external_form_host(link):
            return Result(row.get("row_no", ""), row.get("company_name", ""), row.get("prefecture", ""), row.get("municipality", ""), site, row.get("source_url", ""), row.get("public_email", ""), "あり", link, "外部フォーム", "はい", f"リンク文言: {text[:180]}", str(status), final_url, len(links), scanned_at)
        _, c_final, c_body, _ = await fetch(session, link)
        if c_body:
            ok, kind, why = detect_form(c_final, c_body, text)
            if ok:
                return Result(row.get("row_no", ""), row.get("company_name", ""), row.get("prefecture", ""), row.get("municipality", ""), site, row.get("source_url", ""), row.get("public_email", ""), "あり", c_final, kind, "いいえ" if same_site(final_url, c_final) else "はい", f"リンク文言: {text[:130]} / {why}", str(status), final_url, len(links), scanned_at)

    if not links:
        base = root_url(final_url)
        for path in COMMON_PATHS:
            link = urljoin(base, path)
            if link in checked:
                continue
            checked.add(link)
            c_status, c_final, c_body, _ = await fetch(session, link)
            if c_status in {404, 410} or not c_body:
                continue
            ok, kind, why = detect_form(c_final, c_body, path)
            if ok:
                return Result(row.get("row_no", ""), row.get("company_name", ""), row.get("prefecture", ""), row.get("municipality", ""), site, row.get("source_url", ""), row.get("public_email", ""), "あり", c_final, kind, "いいえ" if same_site(final_url, c_final) else "はい", f"共通パス確認: {path} / {why}", str(status), final_url, len(links), scanned_at)

    status_label = "なし（自動確認）" if status and status < 400 else "要確認"
    return Result(row.get("row_no", ""), row.get("company_name", ""), row.get("prefecture", ""), row.get("municipality", ""), site, row.get("source_url", ""), row.get("public_email", ""), status_label, "", "", "", f"候補リンク{len(links)}件を確認したがフォーム未検出", str(status), final_url, len(links), scanned_at)


async def main(input_csv: Path, output_csv: Path) -> None:
    with input_csv.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    connector = aiohttp.TCPConnector(limit=TOTAL_CONCURRENCY, limit_per_host=PER_HOST, ssl=ssl.create_default_context(), ttl_dns_cache=600)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"}
    async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT, connector=connector, headers=headers) as session:
        semaphore = asyncio.Semaphore(TOTAL_CONCURRENCY)
        async def bounded(row: dict[str, str]) -> Result:
            async with semaphore:
                return await scan_one(session, row)
        tasks = [asyncio.create_task(bounded(row)) for row in rows]
        results: list[Result] = []
        for idx, task in enumerate(asyncio.as_completed(tasks), 1):
            results.append(await task)
            if idx % 100 == 0:
                print(f"completed {idx}/{len(tasks)}", flush=True)
    results.sort(key=lambda item: int(item.row_no) if str(item.row_no).isdigit() else 10**9)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = list(Result.__dataclass_fields__.keys())
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(asdict(item) for item in results)
    from collections import Counter
    print(Counter(item.form_status for item in results), flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: scan_contact_forms.py INPUT.csv OUTPUT.csv")
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2])))
