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
    "Mozilla/5.0 (compatible; PPconnectPublicBusinessResearch/1.0; "
    "+https://ppconnect.co.jp/)"
)
TIMEOUT = aiohttp.ClientTimeout(total=18, connect=7, sock_read=11)
CONCURRENCY = 60
PER_HOST = 3
MAX_BYTES = 2_000_000
FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.co.jp", "yahoo.com", "outlook.com", "hotmail.com",
    "icloud.com", "me.com", "live.jp", "live.com", "nifty.com", "biglobe.ne.jp",
    "ocn.ne.jp", "jcom.zaq.ne.jp", "zaq.ne.jp", "plala.or.jp", "goo.jp",
    "excite.co.jp", "aol.com", "msn.com", "docomo.ne.jp", "ezweb.ne.jp",
    "softbank.ne.jp", "i.softbank.jp", "au.com",
}
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
EXTERNAL_FORM_HOSTS = {
    "docs.google.com", "forms.gle", "form.run", "form-mailer.jp", "ssl.form-mailer.jp",
    "hubspot.com", "hsforms.com", "salesforce.com", "pardot.com", "kintoneapp.com",
    "select-type.com", "coubic.com", "reserva.be", "airreserve.net",
}
NON_CONTACT_PATTERNS = [
    "login", "signin", "search", "site-search", "newsletter", "member", "mypage",
    "recruit", "entry", "apply", "応募", "採用",
]
SPACE_RE = re.compile(r"\s+")
CORP_WORDS = re.compile(r"株式会社|有限会社|合同会社|一般社団法人|公益社団法人|不動産|ホーム|ハウス|エステート|リアルティ|リアルエステート|センター|（株）|\(株\)|（有）|\(有\)")


@dataclass
class Result:
    row_no: str
    company_name: str
    prefecture: str
    municipality: str
    public_email: str
    original_official_site: str
    inferred_official_site: str
    site_status: str
    confidence: str
    title: str
    form_status: str
    contact_form_url: str
    form_type: str
    evidence: str
    researched_at: str


def clean(value: str | None) -> str:
    return SPACE_RE.sub(" ", html.unescape(value or "")).strip()


def email_domain(email: str) -> str:
    value = clean(email).lower()
    if "@" not in value:
        return ""
    return value.rsplit("@", 1)[1].strip(" .")


def normalize_company(value: str) -> str:
    value = CORP_WORDS.sub("", clean(value))
    value = re.sub(r"[^0-9a-zA-Zぁ-んァ-ン一-龥]", "", value).lower()
    return value


def normalize_url(raw: str | None) -> str:
    value = clean(raw)
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value.lstrip("/")
    p = urlparse(value)
    if not p.hostname:
        return ""
    scheme = p.scheme.lower() if p.scheme.lower() in {"http", "https"} else "https"
    return urlunparse((scheme, p.netloc, p.path or "/", "", "", ""))


def same_site(a: str, b: str) -> bool:
    ah = (urlparse(a).hostname or "").lower().removeprefix("www.")
    bh = (urlparse(b).hostname or "").lower().removeprefix("www.")
    return bool(ah and bh and (ah == bh or ah.endswith("." + bh) or bh.endswith("." + ah)))


def is_external_form(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in EXTERNAL_FORM_HOSTS)


def contact_score(text: str, href: str) -> int:
    combined = (text + " " + href).lower()
    score = sum(5 for term in CONTACT_TERMS if term.lower() in combined)
    score += sum(4 for hint in URL_HINTS if hint.lower() in href.lower())
    score -= sum(6 for bad in NON_CONTACT_PATTERNS if bad.lower() in combined)
    if href.lower().startswith(("mailto:", "tel:", "javascript:")):
        return -100
    return score


def candidate_links(page_url: str, body: str) -> list[tuple[int, str, str]]:
    soup = BeautifulSoup(body, "html.parser")
    found: dict[str, tuple[int, str]] = {}
    for tag in soup.find_all(["a", "button"]):
        href = clean(tag.get("href") or tag.get("data-href") or tag.get("data-url"))
        text = clean(tag.get_text(" ", strip=True) + " " + (tag.get("aria-label") or "") + " " + (tag.get("title") or ""))
        if not href:
            continue
        absolute = urljoin(page_url, href)
        if urlparse(absolute).scheme not in {"http", "https"}:
            continue
        score = contact_score(text, absolute)
        if score < 4:
            continue
        old = found.get(absolute)
        if old is None or score > old[0]:
            found[absolute] = (score, text[:180])
    return sorted([(s, u, t) for u, (s, t) in found.items()], reverse=True)[:8]


def detect_form(page_url: str, body: str, context: str = "") -> tuple[bool, str, str]:
    soup = BeautifulSoup(body, "html.parser")
    title = clean(soup.title.get_text(" ", strip=True) if soup.title else "")
    page_context = f"{page_url} {title} {context}".lower()
    for tag in soup.find_all(["iframe", "script", "a"]):
        target = clean(tag.get("src") or tag.get("href"))
        if target:
            target = urljoin(page_url, target)
            if is_external_form(target):
                return True, "外部フォーム", f"外部フォーム: {target[:220]}"
    for form in soup.find_all("form"):
        form_text = clean(form.get_text(" ", strip=True))
        action = clean(form.get("action"))
        combined = f"{page_context} {form_text} {action}".lower()
        fields = form.find_all(["input", "textarea", "select"])
        names = " ".join(clean(x.get("name") or x.get("id") or x.get("placeholder") or x.get("type")) for x in fields).lower()
        contact_signals = sum(term.lower() in combined for term in CONTACT_TERMS)
        field_signals = sum(k in names for k in ["name", "email", "mail", "tel", "phone", "message", "comment", "内容", "氏名", "電話"])
        bad_signals = sum(k in combined for k in NON_CONTACT_PATTERNS)
        if (contact_signals >= 1 and len(fields) >= 2) or (form.find("textarea") and field_signals >= 1) or (field_signals >= 3 and bad_signals == 0):
            kind = "問い合わせフォーム"
            if any(k in combined for k in ["査定", "satei", "assessment"]):
                kind = "査定フォーム"
            elif any(k in combined for k in ["来店予約", "内見予約", "reserve", "reservation"]):
                kind = "予約フォーム"
            return True, kind, f"HTML form検出（入力欄{len(fields)}件、title={title[:100]}）"
    visible = clean(soup.get_text(" ", strip=True)).lower()
    if any(term.lower() in page_context for term in CONTACT_TERMS) and any(k in visible for k in ["確認画面", "送信する", "入力内容", "必須項目", "同意"]):
        return True, "問い合わせフォーム（JS）", f"問い合わせページの送信文言を検出（title={title[:100]}）"
    return False, "", ""


async def fetch(session: aiohttp.ClientSession, url: str) -> tuple[int, str, str, str]:
    try:
        async with session.get(url, allow_redirects=True) as response:
            content_type = (response.headers.get("content-type") or "").lower()
            if content_type and "html" not in content_type:
                return response.status, str(response.url), "", f"non-html:{content_type[:80]}"
            raw = await response.content.read(MAX_BYTES)
            encoding = response.charset or "utf-8"
            try:
                text = raw.decode(encoding, errors="replace")
            except LookupError:
                text = raw.decode("utf-8", errors="replace")
            return response.status, str(response.url), text, ""
    except asyncio.TimeoutError:
        return 0, url, "", "timeout"
    except aiohttp.ClientError as exc:
        return 0, url, "", type(exc).__name__
    except Exception as exc:
        return 0, url, "", type(exc).__name__


async def resolve_site(session: aiohttp.ClientSession, domain: str) -> tuple[int, str, str, str]:
    variants = [
        f"https://{domain}/", f"https://www.{domain}/",
        f"http://{domain}/", f"http://www.{domain}/",
    ]
    for url in variants:
        status, final_url, body, error = await fetch(session, url)
        if body and status and status < 400:
            return status, final_url, body, ""
    return status if 'status' in locals() else 0, final_url if 'final_url' in locals() else variants[0], "", error if 'error' in locals() else "unresolved"


async def scan_one(session: aiohttp.ClientSession, row: dict[str, str]) -> Result:
    now = datetime.now(timezone.utc).isoformat()
    original = normalize_url(row.get("official_site"))
    company = row.get("company_name", "")
    if original:
        return Result(row.get("row_no", ""), company, row.get("prefecture", ""), row.get("municipality", ""), row.get("public_email", ""), original, original, "既存URL", "既存", "", "未実施", "", "", "既存公式サイトあり", now)
    domain = email_domain(row.get("public_email", ""))
    if not domain or domain in FREE_EMAIL_DOMAINS:
        return Result(row.get("row_no", ""), company, row.get("prefecture", ""), row.get("municipality", ""), row.get("public_email", ""), "", "", "対象外", "低", "", "未実施", "", "", "フリーメールまたは無効なドメイン", now)
    status, final_url, body, error = await resolve_site(session, domain)
    if not body:
        return Result(row.get("row_no", ""), company, row.get("prefecture", ""), row.get("municipality", ""), row.get("public_email", ""), "", "", "未解決", "低", "", "未実施", "", "", error or f"HTTP {status}", now)
    soup = BeautifulSoup(body, "html.parser")
    title = clean(soup.title.get_text(" ", strip=True) if soup.title else "")
    page_text = clean(soup.get_text(" ", strip=True))[:10000]
    company_key = normalize_company(company)
    title_key = normalize_company(title)
    body_key = normalize_company(page_text[:3000])
    confidence = "中"
    if company_key and (company_key[:8] in title_key or company_key[:8] in body_key):
        confidence = "高"
    elif urlparse(final_url).hostname and domain.removeprefix("www.") in (urlparse(final_url).hostname or "").removeprefix("www."):
        confidence = "中"
    else:
        confidence = "低"

    ok, form_type, evidence = detect_form(final_url, body, "homepage")
    if ok:
        return Result(row.get("row_no", ""), company, row.get("prefecture", ""), row.get("municipality", ""), row.get("public_email", ""), "", final_url, "解決", confidence, title, "あり", final_url, form_type, evidence, now)
    links = candidate_links(final_url, body)
    for _, link, text in links:
        if is_external_form(link):
            return Result(row.get("row_no", ""), company, row.get("prefecture", ""), row.get("municipality", ""), row.get("public_email", ""), "", final_url, "解決", confidence, title, "あり", link, "外部フォーム", f"リンク文言: {text}", now)
        _, c_final, c_body, _ = await fetch(session, link)
        if c_body:
            found, kind, why = detect_form(c_final, c_body, text)
            if found:
                return Result(row.get("row_no", ""), company, row.get("prefecture", ""), row.get("municipality", ""), row.get("public_email", ""), "", final_url, "解決", confidence, title, "あり", c_final, kind, f"リンク文言: {text} / {why}", now)
    return Result(row.get("row_no", ""), company, row.get("prefecture", ""), row.get("municipality", ""), row.get("public_email", ""), "", final_url, "解決", confidence, title, "なし（自動確認）", "", "", f"候補リンク{len(links)}件", now)


async def main(input_csv: Path, output_csv: Path) -> None:
    with input_csv.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    connector = aiohttp.TCPConnector(limit=CONCURRENCY, limit_per_host=PER_HOST, ssl=ssl.create_default_context(), ttl_dns_cache=600)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5", "Accept-Language": "ja,en;q=0.5"}
    semaphore = asyncio.Semaphore(CONCURRENCY)
    async with aiohttp.ClientSession(timeout=TIMEOUT, connector=connector, headers=headers) as session:
        async def bounded(row: dict[str, str]) -> Result:
            async with semaphore:
                return await scan_one(session, row)
        tasks = [asyncio.create_task(bounded(row)) for row in rows]
        results = [await future for future in asyncio.as_completed(tasks)]
    results.sort(key=lambda x: int(x.row_no) if x.row_no.isdigit() else 10**9)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(results[0]).keys()))
        writer.writeheader()
        writer.writerows(asdict(item) for item in results)
    print(f"rows={len(results)} resolved={sum(x.site_status == '解決' for x in results)} high={sum(x.confidence == '高' for x in results)} forms={sum(x.form_status == 'あり' for x in results)}")


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2])))
