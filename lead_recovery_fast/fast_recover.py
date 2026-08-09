#!/usr/bin/env python3
from __future__ import annotations
import csv, json, re, time, urllib.robotparser
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from urllib.parse import urljoin, urlparse, urlunparse
import requests
from bs4 import BeautifulSoup

BASE='https://www.zennichi.net/hp/kanto_kaiin/pref.asp'
PREFS={'東京都':13,'神奈川県':14,'埼玉県':11,'千葉県':12}
OUT=Path('fast_recovery_output')
EMAIL_RE=re.compile(r'[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}',re.I)
PHONE_RE=re.compile(r'0\d{1,4}[-‐－ー]\d{1,4}[-‐－ー]\d{3,4}')
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0 Safari/537.36'
BAD=('example@','example.','noreply','no-reply','donotreply','do-not-reply','privacy@zennichi','support@zennichi','webmaster@zennichi')
FREE=('gmail.com','yahoo.co.jp','yahoo.com','outlook.jp','outlook.com','hotmail.com','icloud.com','nifty.com','biglobe.ne.jp','ocn.ne.jp','plala.or.jp','jcom.home.ne.jp','t-com.ne.jp')
SKIP_HOST=('zennichi.net','google.','yahoo.','facebook.com','instagram.com','x.com','twitter.com','youtube.com','line.me','suumo.jp','homes.co.jp','athome.co.jp','mapion.')
WORDS=('contact','inquiry','company','about','お問い合わせ','問合せ','会社概要','会社案内')

@dataclass
class Company:
    prefecture:str; company_name:str; phone:str; address:str; list_email:str; profile_url:str; list_source_url:str
@dataclass
class Lead:
    prefecture:str; company_name:str; email:str; phone:str; address:str; profile_url:str; email_source_url:str; list_source_url:str; recovery_method:str; confidence:str

def norm(s:str)->str: return re.sub(r'\s+',' ',(s or '').replace('\u3000',' ')).strip()
def valid(e:str)->bool:
    e=e.lower().strip('.,;:()[]<>\"\'')
    return bool(EMAIL_RE.fullmatch(e)) and not any(x in e for x in BAD) and not e.endswith(('.png','.jpg','.jpeg','.gif','.webp','.svg'))
def emails(text:str)->list[str]:
    out=[]; seen=set(); soup=BeautifulSoup(text,'html.parser')
    for a in soup.select('a[href^="mailto:"]'):
        e=str(a.get('href','')).split(':',1)[-1].split('?',1)[0].strip().lower()
        if valid(e) and e not in seen: seen.add(e); out.append(e)
    for e in EMAIL_RE.findall(text):
        e=e.lower().strip('.,;:()[]<>\"\'')
        if valid(e) and e not in seen: seen.add(e); out.append(e)
    return out

def session()->requests.Session:
    s=requests.Session(); s.headers.update({'User-Agent':UA,'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8','Accept-Language':'ja-JP,ja;q=0.9,en;q=0.7','Connection':'close'}); return s

def get(s:requests.Session,url:str,timeout:int=30)->tuple[str,str]:
    for attempt in range(2):
        try:
            r=s.get(url,timeout=timeout,allow_redirects=True)
            if r.status_code>=400: continue
            for enc in ('cp932','shift_jis',r.encoding,r.apparent_encoding,'utf-8'):
                if not enc: continue
                try:
                    return r.content.decode(enc),r.url
                except Exception: pass
            return r.content.decode('utf-8',errors='replace'),r.url
        except requests.RequestException:
            if attempt==0: time.sleep(1)
    return '',url

def parse_list(text:str,pref:str,url:str)->list[Company]:
    soup=BeautifulSoup(text,'html.parser'); out=[]
    for tr in soup.find_all('tr'):
        links=[a for a in tr.find_all('a',href=True) if '/m/' in urljoin(url,str(a.get('href','')))]
        if not links: continue
        raw=norm(tr.get_text(' | ',strip=True))
        if pref not in raw: continue
        a=next((x for x in links if 'ホームページ' in norm(x.get_text(' ',strip=True))),links[0])
        name=re.sub(r'のホームページ$','',norm(a.get_text(' ',strip=True))).strip()
        profile=urljoin(url,str(a.get('href','')))
        es=emails(str(tr)); le=es[0] if es else ''
        pm=PHONE_RE.search(raw); phone=pm.group(0).replace('‐','-').replace('－','-').replace('ー','-') if pm else ''
        address=''; idx=raw.find(pref)
        if idx>=0: address=norm(re.split(r'\s*\|\s*0\d{1,4}[-‐－ー]',raw[idx:],maxsplit=1)[0])[:300]
        out.append(Company(pref,name,phone,address,le,profile,url))
    return out

def ext_links(text:str,base:str)->list[str]:
    soup=BeautifulSoup(text,'html.parser'); ranked=[]; seen=set()
    for a in soup.find_all('a',href=True):
        href=str(a.get('href','')).strip()
        if not href or href.lower().startswith(('mailto:','javascript:','tel:','#')): continue
        u=urljoin(base,href); p=urlparse(u); host=p.netloc.lower()
        if p.scheme not in ('http','https') or any(x in host for x in SKIP_HOST): continue
        u=urlunparse((p.scheme,p.netloc,p.path or '/','','',''))
        if u in seen: continue
        seen.add(u); label=(norm(a.get_text(' ',strip=True))+' '+u).lower(); score=2 if any(w.lower() in label for w in WORDS) else 0
        ranked.append((score,u))
    ranked.sort(key=lambda x:(-x[0],len(x[1]))); return [u for _,u in ranked[:3]]

def internal_links(text:str,base:str)->list[str]:
    soup=BeautifulSoup(text,'html.parser'); host=urlparse(base).netloc.lower(); out=[]; seen=set()
    for a in soup.find_all('a',href=True):
        u=urljoin(base,str(a.get('href',''))).split('#',1)[0]; label=(norm(a.get_text(' ',strip=True))+' '+u).lower()
        if urlparse(u).netloc.lower()==host and any(w.lower() in label for w in WORDS) and u not in seen:
            seen.add(u); out.append(u)
    return out[:2]

def source_accept(email:str,source:str,method:str)->bool:
    if 'Zennichi' in method: return True
    ed=email.split('@')[-1].lower(); host=urlparse(source).netloc.lower().split(':')[0]
    host=host[4:] if host.startswith('www.') else host
    return ed in FREE or host==ed or host.endswith('.'+ed) or ed.endswith('.'+host)

def recover(c:Company)->list[Lead]:
    s=session(); pages=[]; found=[]; root=c.profile_url.rstrip('/')+'/'
    for u in [root,urljoin(root,'kaisha.asp'),urljoin(root,'link.asp'),urljoin(root,'toi.asp')]:
        text,final=get(s,u,18)
        if text:
            pages.append((text,final))
            for e in emails(text): found.append((e,final,'Zennichi member public page'))
        time.sleep(.1)
    ex=[]
    for text,u in pages: ex.extend(ext_links(text,u))
    for u in list(dict.fromkeys(ex))[:3]:
        text,final=get(s,u,15)
        if not text: continue
        for e in emails(text):
            if source_accept(e,final,'Public official website'): found.append((e,final,'Public official website'))
        for child in internal_links(text,final):
            ct,cf=get(s,child,12)
            for e in emails(ct):
                if source_accept(e,cf,'Public official website contact/company page'): found.append((e,cf,'Public official website contact/company page'))
    out=[]; seen=set()
    for e,src,method in found:
        if e in seen: continue
        seen.add(e); out.append(Lead(c.prefecture,c.company_name,e,c.phone,c.address,c.profile_url,src,c.list_source_url,method,'high' if c.company_name and (c.phone or c.address) else 'medium'))
    return out

def main():
    OUT.mkdir(exist_ok=True); s=session(); companies={}; existing=set()
    for pref,code in PREFS.items():
        empty=0
        for page in range(1,201):
            u=f'{BASE}?p={code}&pg={page}&s='; text,_=get(s,u,25); rows=parse_list(text,pref,u) if text else []
            print('list',pref,page,len(rows),flush=True)
            for c in rows:
                companies[c.profile_url]=c
                if c.list_email: existing.add(c.list_email.lower())
            empty=empty+1 if not rows else 0
            if empty>=3: break
            time.sleep(.25)
    missing=[c for c in companies.values() if not c.list_email]
    print('companies',len(companies),'missing',len(missing),flush=True)
    recovered={}; lock=Lock()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(recover,c):c for c in missing}
        for i,f in enumerate(as_completed(futures),1):
            c=futures[f]
            try: rs=f.result()
            except Exception as exc:
                print('error',c.company_name,repr(exc),flush=True); continue
            with lock:
                for r in rs:
                    if r.email not in existing and r.email not in recovered: recovered[r.email]=r
                count=len(recovered)
            print('recover',i,'/',len(missing),c.company_name,'found',len(rs),'total',count,flush=True)
            if count>=180:
                for pending in futures: pending.cancel()
                break
    rows=[asdict(x) for x in recovered.values()]; rows.sort(key=lambda x:(x['prefecture'],x['company_name'],x['email']))
    fields=list(Lead.__dataclass_fields__.keys())
    with (OUT/'recovered_emails.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    (OUT/'recovered_emails.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    stats={'all_companies':len(companies),'missing_list_email':len(missing),'recovered_unique_emails':len(rows)}
    (OUT/'stats.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(stats,ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__': main()
