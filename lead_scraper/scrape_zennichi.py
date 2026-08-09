#!/usr/bin/env python3
"""Collect public business contact data from the Zennichi Kanto member directory.

The script is deliberately conservative:
- public directory pages only
- no login/CAPTCHA bypass
- one request per second
- saves source URL and raw context for review
- never sends email
"""
from __future__ import annotations

import csv
import hashlib
import html as html_lib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

BASE = "https://www.zennichi.net/hp/kanto_kaiin/pref.asp"
PREFS = {
    "東京都": 13,
    "神奈川県": 14,
    "埼玉県": 11,
    "千葉県": 12,
}
OUT = Path("output")
DEBUG = OUT / "debug"
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:0\d{1,4}[-‐－ー]\d{1,4}[-‐－ー]\d{3,4}|0\d{9,10})")
POST_RE = re.compile(r"(?:〒\s*)?(\d{3})[-‐－ー]?(\d{4})")
COMPANY_MARKERS = ("株式会社", "（株）", "(株)", "有限会社", "（有）", "(有)", "合同会社", "不動産", "住宅", "ホーム", "ハウス", "エステート", "リアルティ", "住建", "地所")
LABEL_PREFIXES = ("TEL", "ＴＥＬ", "FAX", "ＦＡＸ", "E-MAIL", "EMAIL", "メール", "所在地", "住所", "免許", "代表", "営業時間", "定休日", "ホームページ", "WEB")


@dataclass
class Lead:
    prefecture: str
    company_name: str
    email: str
    phone: str
    postal_code: str
    address: str
    website_url: str
    source_url: str
    source_page: int
    source_type: str
    raw_context: str
    confidence: str


def normalize_space(value: str) -> str:
    value = html_lib.unescape(value or "")
    value = value.replace("\u3000", " ")
    return re.sub(r"\s+", " ", value).strip()


def decode_response(resp: requests.Response) -> str:
    # The directory is historically Shift-JIS/CP932. requests can mis-detect it.
    for enc in (resp.encoding, "cp932", "shift_jis", resp.apparent_encoding, "utf-8"):
        if not enc:
            continue
        try:
            text = resp.content.decode(enc)
            if "会員" in text or "不動産" in text or "メール" in text:
                return text
        except (UnicodeDecodeError, LookupError):
            pass
    return resp.content.decode("utf-8", errors="replace")


def iter_email_nodes(soup: BeautifulSoup) -> Iterable[tuple[str, Tag | None]]:
    seen: set[str] = set()
    for a in soup.select('a[href^="mailto:"]'):
        href = a.get("href", "")
        email = href.split(":", 1)[-1].split("?", 1)[0].strip()
        if EMAIL_RE.fullmatch(email) and email.lower() not in seen:
            seen.add(email.lower())
            yield email, a
    # Some directory pages render email as plain text.
    for node in soup.find_all(string=EMAIL_RE):
        for email in EMAIL_RE.findall(str(node)):
            key = email.lower()
            if key not in seen:
                seen.add(key)
                yield email, node.parent if isinstance(node.parent, Tag) else None
    # Last-resort raw HTML extraction catches uncommon markup.
    for email in EMAIL_RE.findall(str(soup)):
        key = email.lower()
        if key not in seen:
            seen.add(key)
            yield email, None


def choose_context(node: Tag | None, soup: BeautifulSoup, email: str) -> Tag:
    if node is None:
        return soup
    cur: Tag | None = node
    best = node
    while cur is not None:
        text = normalize_space(cur.get_text(" | ", strip=True))
        if email.lower() in text.lower() or "mailto:" in str(cur).lower():
            best = cur
        # Stop once the block has enough identifying information but is not huge.
        if len(text) >= 20 and len(text) <= 1800 and (PHONE_RE.search(text) or POST_RE.search(text)):
            return cur
        parent = cur.parent
        cur = parent if isinstance(parent, Tag) else None
    return best


def extract_company(container: Tag, context: str, email: str) -> str:
    candidates: list[str] = []
    for selector in ("strong", "b", "h1", "h2", "h3", "h4", "a"):
        for tag in container.select(selector):
            if tag.name == "a" and str(tag.get("href", "")).lower().startswith("mailto:"):
                continue
            txt = normalize_space(tag.get_text(" ", strip=True))
            if txt and email.lower() not in txt.lower() and len(txt) <= 100:
                candidates.append(txt)
    lines = [normalize_space(x) for x in re.split(r"[|\n\r]+", container.get_text("\n", strip=True))]
    candidates.extend([x for x in lines if x and len(x) <= 100])
    for c in candidates:
        upper = c.upper()
        if upper.startswith(LABEL_PREFIXES):
            continue
        if any(marker in c for marker in COMPANY_MARKERS):
            return c
    # Fall back to first meaningful line.
    for c in candidates:
        if c and not c.upper().startswith(LABEL_PREFIXES) and not PHONE_RE.fullmatch(c):
            return c
    return ""


def extract_address(context: str, prefecture: str) -> tuple[str, str]:
    postal = ""
    m = POST_RE.search(context)
    if m:
        postal = f"{m.group(1)}-{m.group(2)}"
    # Capture from prefecture name until a common next-field label.
    idx = context.find(prefecture)
    if idx >= 0:
        tail = context[idx:]
        tail = re.split(r"\s*(?:TEL|ＴＥＬ|FAX|ＦＡＸ|E-?MAIL|メール|免許番号|代表者|営業時間|定休日)\s*", tail, maxsplit=1, flags=re.I)[0]
        return postal, normalize_space(tail)[:300]
    return postal, ""


def extract_phone(context: str) -> str:
    m = PHONE_RE.search(context)
    if not m:
        return ""
    return m.group(0).replace("‐", "-").replace("－", "-").replace("ー", "-")


def extract_website(container: Tag, source_url: str) -> str:
    for a in container.select("a[href]"):
        href = str(a.get("href", "")).strip()
        if not href or href.lower().startswith(("mailto:", "javascript:", "#")):
            continue
        full = urljoin(source_url, href)
        host = urlparse(full).netloc.lower()
        # Keep an external business site when one is present; otherwise directory profile URL.
        if host and "zennichi.net" not in host:
            return full
    return ""


def parse_page(html: str, prefecture: str, page_no: int, source_url: str) -> list[Lead]:
    soup = BeautifulSoup(html, "html.parser")
    leads: list[Lead] = []
    for email, node in iter_email_nodes(soup):
        container = choose_context(node, soup, email)
        context = normalize_space(container.get_text(" | ", strip=True))
        company = extract_company(container, context, email)
        phone = extract_phone(context)
        postal, address = extract_address(context, prefecture)
        website = extract_website(container, source_url)
        confidence = "high" if company and (phone or address) else "medium" if company else "low"
        leads.append(
            Lead(
                prefecture=prefecture,
                company_name=company,
                email=email.lower(),
                phone=phone,
                postal_code=postal,
                address=address,
                website_url=website,
                source_url=source_url,
                source_page=page_no,
                source_type="全日本不動産協会 関東流通センター公開会員一覧",
                raw_context=context[:1800],
                confidence=confidence,
            )
        )
    return leads


def main() -> None:
    OUT.mkdir(exist_ok=True)
    DEBUG.mkdir(exist_ok=True)
    session = requests.Session()
    session.headers.update({
        "User-Agent": "PPconnect-public-directory-research/1.0 (+business research; contact via company website)",
        "Accept-Language": "ja,en;q=0.8",
    })
    all_leads: dict[str, Lead] = {}
    stats: dict[str, dict[str, int | str]] = {}

    for pref, code in PREFS.items():
        pref_new = 0
        pages_fetched = 0
        consecutive_empty = 0
        previous_digest = ""
        for page in range(1, 201):
            url = f"{BASE}?p={code}&pg={page}&s="
            resp = session.get(url, timeout=40)
            resp.raise_for_status()
            text = decode_response(resp)
            digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
            if page == 1:
                (DEBUG / f"{code}_page1.html").write_text(text, encoding="utf-8")
            pages_fetched += 1
            parsed = parse_page(text, pref, page, url)
            before = len(all_leads)
            for lead in parsed:
                key = lead.email.lower()
                if key not in all_leads or (all_leads[key].confidence != "high" and lead.confidence == "high"):
                    all_leads[key] = lead
            added = len(all_leads) - before
            pref_new += added
            print(f"{pref} page={page} emails={len(parsed)} added={added} total={len(all_leads)}")

            # Stop on repeat page or several pages with no emails. Keep enough tolerance for sparse pages.
            if digest == previous_digest:
                print(f"Stopping {pref}: repeated page content at page {page}")
                break
            previous_digest = digest
            if not parsed:
                consecutive_empty += 1
            else:
                consecutive_empty = 0
            if consecutive_empty >= 3:
                print(f"Stopping {pref}: 3 consecutive pages without email")
                break
            time.sleep(1.0)
        stats[pref] = {"pages_fetched": pages_fetched, "unique_emails_added": pref_new}

    rows = [asdict(x) for x in all_leads.values()]
    rows.sort(key=lambda x: (x["prefecture"], x["company_name"], x["email"]))
    fieldnames = list(Lead.__dataclass_fields__.keys())
    with (OUT / "zennichi_leads.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "zennichi_leads.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    stats["TOTAL"] = {"unique_emails": len(rows)}
    (OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
