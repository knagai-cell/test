#!/usr/bin/env python3
"""Collect public business emails from Chinkan member detail pages.

Safeguards: public pages only, no authentication/CAPTCHA bypass, small parallelism,
exact source URL retained, no email sending.
"""
from __future__ import annotations
import csv, json, re, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

OUT=Path('chinkan_output')
TARGET_PREFS=('東京都','神奈川県','埼玉県','千葉県')
EMAIL_RE=re.compile(r'[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}',re.I)
PHONE_RE=re.compile(r'0\d{1,4}[-‐－ー]\d{1,4}[-‐－ー]\d{3,4}')
BAD=('example@','example.','noreply','no-reply','donotreply','do-not-reply','webmaster@chinkan','support@chinkan')
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0 Safari/537.36'
SKIP_HEADINGS={'全宅管理','sns','スタッフ紹介','staff','店舗概要','outline','ご提供サービス内容','service','オーナー様向けサービス','ユーザー様向けサービス','取得資格項目'}

@dataclass
class Lead:
    prefecture:str
    company_name:str
    email:str
    phone:str
    address:str
    website_url:str
    source_url:str
    source_type:str
    member_id:str


def norm(s): return re.sub(r'\s+',' ',str(s or '').replace('\u3000',' ')).strip()
def valid_email(e):
    e=str(e or '').lower().strip('.,;:()[]<>\"\'')
    return bool(EMAIL_RE.fullmatch(e)) and not any(x in e for x in BAD) and not e.endswith(('.png','.jpg','.jpeg','.gif','.webp','.svg'))

def get_page(member_id:int):
    mid=f'{member_id:05d}'; url=f'https://chinkan.jp/shop/detail/{mid}.html'
    try:
        r=requests.get(url,headers={'User-Agent':UA,'Accept-Language':'ja-JP,ja;q=0.9','Connection':'close'},timeout=10,allow_redirects=True)
    except requests.RequestException:
        return None
    if r.status_code!=200 or len(r.content)<1000: return None
    r.encoding=r.apparent_encoding or 'utf-8'
    text=r.text
    if '事務所所在地' not in text or '宅建免許番号' not in text: return None
    soup=BeautifulSoup(text,'html.parser'); page_text=norm(soup.get_text(' | ',strip=True))
    pref=next((p for p in TARGET_PREFS if p in page_text),None)
    if not pref: return None
    emails=[]; seen=set()
    for a in soup.select('a[href^="mailto:"]'):
        e=str(a.get('href','')).split(':',1)[-1].split('?',1)[0].lower().strip()
        if valid_email(e) and e not in seen: seen.add(e);emails.append(e)
    for e in EMAIL_RE.findall(text):
        e=e.lower().strip('.,;:()[]<>\"\'')
        if valid_email(e) and e not in seen: seen.add(e);emails.append(e)
    if not emails: return None
    company=''
    for tag in soup.find_all(['h1','h2','h3','h4']):
        h=norm(tag.get_text(' ',strip=True))
        if h and h not in SKIP_HEADINGS and len(h)<100 and not h.startswith(('オーナー','ユーザー')):
            company=h; break
    if not company: return None
    # Extract address from label to TEL.
    address=''
    m=re.search(r'事務所所在地\s*[| ]+(.+?)\s*[| ]+TEL',page_text,re.I)
    if m: address=norm(m.group(1))[:300]
    phone=''; pm=PHONE_RE.search(page_text)
    if pm: phone=pm.group(0).replace('‐','-').replace('－','-').replace('ー','-')
    website=''
    for a in soup.find_all('a',href=True):
        href=str(a.get('href','')).strip(); host=urlparse(href).netloc.lower()
        if href.startswith(('http://','https://')) and host and 'chinkan.jp' not in host and 'facebook.com' not in host and 'instagram.com' not in host and 'twitter.com' not in host and 'x.com' not in host:
            website=href; break
    return [Lead(pref,company,e,phone,address,website,url,'全国賃貸不動産管理業協会 公開会員店紹介',mid) for e in emails]

def main():
    OUT.mkdir(exist_ok=True); found={}; processed=0
    # Sequential chunks let us stop without scheduling all 11k requests at once.
    for start in range(1,11001,250):
        ids=range(start,min(start+250,11001))
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures={pool.submit(get_page,i):i for i in ids}
            for f in as_completed(futures):
                processed+=1
                try: rows=f.result()
                except Exception as exc:
                    print('error',futures[f],repr(exc),flush=True);continue
                if not rows: continue
                for r in rows:
                    if r.email not in found: found[r.email]=r
                print('found',rows[0].member_id,rows[0].company_name,len(rows),'unique',len(found),'processed',processed,flush=True)
        print('chunk',start,'unique',len(found),flush=True)
        if len(found)>=350: break
        time.sleep(.4)
    rows=[asdict(x) for x in found.values()];rows.sort(key=lambda x:(TARGET_PREFS.index(x['prefecture']),x['company_name'],x['email']))
    fields=list(Lead.__dataclass_fields__.keys())
    with (OUT/'chinkan_leads.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    (OUT/'chinkan_leads.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    stats={'processed_ids':processed,'unique_public_emails':len(rows),'by_prefecture':{p:sum(1 for r in rows if r['prefecture']==p) for p in TARGET_PREFS}}
    (OUT/'stats.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(stats,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
