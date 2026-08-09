#!/usr/bin/env python3
"""Recover additional public business emails for Zennichi members that have no list email.

Scope and safeguards:
- public pages only; no authentication or CAPTCHA bypass
- crawls only the member mini-site and a small number of publicly linked official pages
- respects robots.txt for external domains when it can be read
- conservative request pacing and small per-company crawl budget
- stores exact source URL for every recovered email
- never sends email
"""
from __future__ import annotations

import csv
import json
import math
import re
import time
import urllib.robotparser
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

BASE = "https://www.zennichi.net/hp/kanto_kaiin/pref.asp"
PREFS = {"東京都": 13, "神奈川県": 14, "埼玉県": 11, "千葉県": 12}
OUT = Path("recovery_output")
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"0\d{1,4}[-‐－ー]\d{1,4}[-‐－ー]\d{3,4}")
BAD_EMAIL_PARTS = (
    "example.", "example@", "noreply", "no-reply", "donotreply", "do-not-reply",
    "privacy@zennichi", "webmaster@zennichi", "support@zennichi",
)
GENERIC_EXTERNAL_HOSTS = (
    "zennichi.net", "google.", "yahoo.", "facebook.com", "instagram.com", "twitter.com",
    "x.com", "youtube.com", "line.me", "suumo.jp", "homes.co.jp", "athome.co.jp",
    "mapion.co.jp", "goo.ne.jp", "bing.com", "apple.com",
)
RELEVANT_LINK_WORDS = ("お問い合わせ", "問合せ", "contact", "inquiry", "会社", "company", "about", "概要")


@dataclass
class Company:
    prefecture: str
    company_name: str
    phone: str
    address: str
    list_email: str
    profile_url: str
    list_source_url: str
    page_no: int


@dataclass
class Recovered:
    prefecture: str
    company_name: str
    email: str
    phone: str
    address: str
    profile_url: str
    email_source_url: str
    list_source_url: str
    recovery_method: str
    confidence: str


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\u3000", " ")).strip()


def valid_email(value: str) -> bool:
    e = value.strip().lower().strip(".,;:()[]<>\"'")
    if not EMAIL_RE.fullmatch(e):
        return False
    if any(x in e for x in BAD_EMAIL_PARTS):
        return False
    if e.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
        return False
    return True


def emails_from_html(text: str) -> list[str]:
    soup = BeautifulSoup(text, "html.parser")
    found: list[str] = []
    seen: set[str] = set()
    for a in soup.select('a[href^="mailto:"]'):
        email = str(a.get("href", "")).split(":", 1)[-1].split("?", 1)[0].strip().lower()
        if valid_email(email) and email not in seen:
            seen.add(email); found.append(email)
    for email in EMAIL_RE.findall(text):
        email = email.lower().strip(".,;:()[]<>\"'")
        if valid_email(email) and email not in seen:
            seen.add(email); found.append(email)
    return found


def decode_response(resp: requests.Response) -> str:
    for enc in (resp.encoding, "cp932", "shift_jis", resp.apparent_encoding, "utf-8"):
        if not enc:
            continue
        try:
            txt = resp.content.decode(enc)
            if "不動産" in txt or "会社" in txt or "メール" in txt or "contact" in txt.lower():
                return txt
        except Exception:
            pass
    return resp.content.decode("utf-8", errors="replace")


def fetch(session: requests.Session, url: str, timeout: int = 20) -> tuple[str, str]:
    try:
        resp = session.get(url, timeout=timeout, allow_redirects=True)
        if resp.status_code >= 400:
            return "", url
        return decode_response(resp), resp.url
    except requests.RequestException:
        return "", url


def parse_company_rows(html: str, prefecture: str, page_no: int, source_url: str) -> list[Company]:
    soup = BeautifulSoup(html, "html.parser")
    companies: list[Company] = []
    seen_profiles: set[str] = set()
    for tr in soup.find_all("tr"):
        links = [a for a in tr.find_all("a", href=True) if "/m/" in urljoin(source_url, a.get("href", ""))]
        if not links:
            continue
        text = norm(tr.get_text(" | ", strip=True))
        if prefecture not in text:
            continue
        homepage_link = next((a for a in links if "ホームページ" in norm(a.get_text(" ", strip=True))), links[0])
        profile_url = urljoin(source_url, homepage_link.get("href", ""))
        if profile_url in seen_profiles:
            continue
        seen_profiles.add(profile_url)
        company_name = norm(homepage_link.get_text(" ", strip=True))
        company_name = re.sub(r"のホームページ$", "", company_name).strip()
        list_emails = emails_from_html(str(tr))
        list_email = list_emails[0] if list_emails else ""
        phone_match = PHONE_RE.search(text)
        phone = phone_match.group(0).replace("‐", "-").replace("－", "-").replace("ー", "-") if phone_match else ""
        address = ""
        idx = text.find(prefecture)
        if idx >= 0:
            tail = text[idx:]
            address = norm(re.split(r"\s*\|\s*0\d{1,4}[-‐－ー]", tail, maxsplit=1)[0])[:300]
        companies.append(Company(prefecture, company_name, phone, address, list_email, profile_url, source_url, page_no))
    return companies


def normalize_root(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, "/", "", "", ""))


def robots_allowed(session: requests.Session, url: str, cache: dict[str, bool]) -> bool:
    p = urlparse(url)
    root = f"{p.scheme}://{p.netloc}"
    if root in cache:
        return cache[root]
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(root + "/robots.txt")
    try:
        rp.read()
        allowed = rp.can_fetch(session.headers.get("User-Agent", "*"), url)
    except Exception:
        allowed = True
    cache[root] = allowed
    return allowed


def external_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    ranked: list[tuple[int, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = str(a.get("href", "")).strip()
        if not href or href.lower().startswith(("mailto:", "javascript:", "tel:", "#")):
            continue
        full = urljoin(base_url, href)
        p = urlparse(full)
        if p.scheme not in ("http", "https"):
            continue
        host = p.netloc.lower()
        if any(x in host for x in GENERIC_EXTERNAL_HOSTS):
            continue
        clean = urlunparse((p.scheme, p.netloc, p.path or "/", "", "", ""))
        if clean in seen:
            continue
        seen.add(clean)
        text = norm(a.get_text(" ", strip=True)).lower()
        score = 2 if any(w.lower() in text or w.lower() in clean.lower() for w in RELEVANT_LINK_WORDS) else 0
        ranked.append((score, clean))
    ranked.sort(key=lambda x: (-x[0], len(x[1])))
    return [u for _, u in ranked]


def relevant_internal_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_host = urlparse(base_url).netloc.lower()
    out: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        text = norm(a.get_text(" ", strip=True)).lower()
        href = str(a.get("href", ""))
        full = urljoin(base_url, href)
        if urlparse(full).netloc.lower() != base_host:
            continue
        if not any(w.lower() in text or w.lower() in full.lower() for w in RELEVANT_LINK_WORDS):
            continue
        clean = full.split("#", 1)[0]
        if clean not in seen:
            seen.add(clean); out.append(clean)
    return out[:3]


def main() -> None:
    OUT.mkdir(exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "PPconnect-public-business-research/1.0", "Accept-Language": "ja,en;q=0.8"})

    companies_by_profile: dict[str, Company] = {}
    for pref, code in PREFS.items():
        empty = 0
        for page in range(1, 201):
            source_url = f"{BASE}?p={code}&pg={page}&s="
            html, _ = fetch(session, source_url, 30)
            rows = parse_company_rows(html, pref, page, source_url) if html else []
            print(f"list {pref} page={page} companies={len(rows)}")
            for c in rows:
                companies_by_profile[c.profile_url] = c
            if not rows:
                empty += 1
            else:
                empty = 0
            if empty >= 3:
                break
            time.sleep(0.45)

    missing = [c for c in companies_by_profile.values() if not c.list_email]
    print(f"companies={len(companies_by_profile)} missing_list_email={len(missing)}")

    recovered: dict[str, Recovered] = {}
    robots_cache: dict[str, bool] = {}
    for index, company in enumerate(missing, 1):
        profile_root = company.profile_url.rstrip("/") + "/"
        zennichi_pages = [profile_root, urljoin(profile_root, "kaisha.asp"), urljoin(profile_root, "link.asp"), urljoin(profile_root, "toi.asp")]
        profile_htmls: list[tuple[str, str]] = []
        company_emails: list[tuple[str, str, str]] = []
        for url in zennichi_pages:
            text, final_url = fetch(session, url, 15)
            if not text:
                continue
            profile_htmls.append((text, final_url))
            for email in emails_from_html(text):
                company_emails.append((email, final_url, "Zennichi member public page"))
            time.sleep(0.2)

        # Follow a very small number of public external links from the member mini-site.
        ext_candidates: list[str] = []
        for text, page_url in profile_htmls:
            ext_candidates.extend(external_links(text, page_url))
        ext_seen: set[str] = set()
        for ext_url in ext_candidates:
            if ext_url in ext_seen:
                continue
            ext_seen.add(ext_url)
            if len(ext_seen) > 3:
                break
            if not robots_allowed(session, ext_url, robots_cache):
                continue
            text, final_url = fetch(session, ext_url, 15)
            if not text:
                continue
            for email in emails_from_html(text):
                company_emails.append((email, final_url, "Public official website"))
            for child in relevant_internal_links(text, final_url):
                if not robots_allowed(session, child, robots_cache):
                    continue
                child_text, child_final = fetch(session, child, 12)
                for email in emails_from_html(child_text):
                    company_emails.append((email, child_final, "Public official website contact/company page"))
                time.sleep(0.15)
            time.sleep(0.25)

        for email, source, method in company_emails:
            if email in recovered:
                continue
            recovered[email] = Recovered(
                prefecture=company.prefecture,
                company_name=company.company_name,
                email=email,
                phone=company.phone,
                address=company.address,
                profile_url=company.profile_url,
                email_source_url=source,
                list_source_url=company.list_source_url,
                recovery_method=method,
                confidence="high" if source.startswith("http") else "medium",
            )
        print(f"recover {index}/{len(missing)} {company.company_name} found={len(company_emails)} total_unique={len(recovered)}")
        # The task only needs enough additional records to cross 2,000 after merge; collect a buffer.
        if len(recovered) >= 220:
            print("Reached recovery buffer target; stopping early.")
            break

    rows = [asdict(x) for x in recovered.values()]
    rows.sort(key=lambda x: (x["prefecture"], x["company_name"], x["email"]))
    fields = list(Recovered.__dataclass_fields__.keys())
    with (OUT / "recovered_emails.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    (OUT / "recovered_emails.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "all_companies.json").write_text(json.dumps([asdict(x) for x in companies_by_profile.values()], ensure_ascii=False, indent=2), encoding="utf-8")
    stats = {"all_companies": len(companies_by_profile), "missing_list_email": len(missing), "recovered_unique_emails": len(rows)}
    (OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
