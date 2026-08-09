#!/usr/bin/env python3
"""Crawl Chinkan public prefecture/city indexes and detail pages for public emails."""
from __future__ import annotations
import csv,json,re,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from dataclasses import dataclass,asdict
from pathlib import Path
from urllib.parse import urljoin,urlparse
import requests
from bs4 import BeautifulSoup

PREFS={'東京都':13,'神奈川県':14,'埼玉県':11,'千葉県':12}
OUT=Path('chinkan_index_output'); UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0 Safari/537.36'
EMAIL_RE=re.compile(r'[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}',re.I);PHONE_RE=re.compile(r'0\d{1,4}[-‐－ー]\d{1,4}[-‐－ー]\d{3,4}')
BAD=('example@','example.','noreply','no-reply','donotreply','do-not-reply','webmaster@chinkan','support@chinkan')
SKIP={'全宅管理','sns','スタッフ紹介','staff','店舗概要','outline','ご提供サービス内容','service','オーナー様向けサービス','ユーザー様向けサービス','取得資格項目'}
@dataclass
class Lead:
 prefecture:str;company_name:str;email:str;phone:str;address:str;website_url:str;source_url:str;source_type:str;member_id:str

def norm(s):return re.sub(r'\s+',' ',str(s or '').replace('\u3000',' ')).strip()
def valid(e):
 e=str(e or '').lower().strip('.,;:()[]<>\"\'');return bool(EMAIL_RE.fullmatch(e)) and not any(x in e for x in BAD) and not e.endswith(('.png','.jpg','.jpeg','.gif','.webp','.svg'))
def fetch(url,timeout=20):
 try:
  r=requests.get(url,headers={'User-Agent':UA,'Accept-Language':'ja-JP,ja;q=0.9','Connection':'close'},timeout=timeout,allow_redirects=True)
  if r.status_code!=200:return '',r.url
  r.encoding=r.apparent_encoding or 'utf-8';return r.text,r.url
 except requests.RequestException:return '',url

def links(text,base,pattern):
 soup=BeautifulSoup(text,'html.parser');out=[];seen=set()
 for a in soup.find_all('a',href=True):
  u=urljoin(base,str(a.get('href',''))).split('#',1)[0]
  if re.search(pattern,u) and u not in seen:seen.add(u);out.append(u)
 return out

def parse_detail(url):
 text,final=fetch(url,15)
 if not text or '事務所所在地' not in text or '宅建免許番号' not in text:return []
 soup=BeautifulSoup(text,'html.parser');plain=norm(soup.get_text(' | ',strip=True));pref=next((p for p in PREFS if p in plain),None)
 if not pref:return []
 es=[];seen=set()
 for a in soup.select('a[href^="mailto:"]'):
  e=str(a.get('href','')).split(':',1)[-1].split('?',1)[0].strip().lower()
  if valid(e) and e not in seen:seen.add(e);es.append(e)
 for e in EMAIL_RE.findall(text):
  e=e.lower().strip('.,;:()[]<>\"\'')
  if valid(e) and e not in seen:seen.add(e);es.append(e)
 if not es:return []
 company=''
 for tag in soup.find_all(['h1','h2','h3','h4']):
  h=norm(tag.get_text(' ',strip=True))
  if h and h not in SKIP and len(h)<100 and not h.startswith(('オーナー','ユーザー')):company=h;break
 if not company:return []
 m=re.search(r'事務所所在地\s*[| ]+(.+?)\s*[| ]+TEL',plain,re.I);address=norm(m.group(1))[:300] if m else ''
 pm=PHONE_RE.search(plain);phone=pm.group(0).replace('‐','-').replace('－','-').replace('ー','-') if pm else ''
 website=''
 for a in soup.find_all('a',href=True):
  href=str(a.get('href','')).strip();host=urlparse(href).netloc.lower()
  if href.startswith(('http://','https://')) and host and 'chinkan.jp' not in host and not any(x in host for x in ('facebook.com','instagram.com','twitter.com','x.com')):website=href;break
 mid=re.search(r'/detail/(\d+)\.html',final);member=mid.group(1) if mid else ''
 return [Lead(pref,company,e,phone,address,website,final,'全国賃貸不動産管理業協会 公開会員店紹介',member) for e in es]

def main():
 OUT.mkdir(exist_ok=True);city_urls=[]
 for pref,code in PREFS.items():
  url=f'https://chinkan.jp/shop/town_search/{code}/';text,final=fetch(url,30);ls=links(text,final,r'/shop/info/\d+/?$');print('town',pref,len(ls),flush=True);city_urls.extend(ls)
 city_urls=list(dict.fromkeys(city_urls));detail_urls=[]
 with ThreadPoolExecutor(max_workers=8) as pool:
  future={pool.submit(fetch,u,20):u for u in city_urls}
  for f in as_completed(future):
   text,final=f.result();detail_urls.extend(links(text,final,r'/shop/detail/\d+\.html$'))
 detail_urls=list(dict.fromkeys(detail_urls));print('city_pages',len(city_urls),'detail_urls',len(detail_urls),flush=True)
 found={}
 with ThreadPoolExecutor(max_workers=10) as pool:
  future={pool.submit(parse_detail,u):u for u in detail_urls}
  for i,f in enumerate(as_completed(future),1):
   try:rs=f.result()
   except Exception as exc:print('error',future[f],repr(exc),flush=True);continue
   for r in rs:
    if r.email not in found:found[r.email]=r
   if rs:print('found',rs[0].member_id,rs[0].company_name,len(rs),'unique',len(found),i,'/',len(detail_urls),flush=True)
 rows=[asdict(x) for x in found.values()];rows.sort(key=lambda x:(list(PREFS).index(x['prefecture']),x['company_name'],x['email']))
 fields=list(Lead.__dataclass_fields__.keys())
 with (OUT/'chinkan_leads.csv').open('w',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 (OUT/'chinkan_leads.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
 stats={'city_pages':len(city_urls),'detail_pages':len(detail_urls),'unique_public_emails':len(rows),'by_prefecture':{p:sum(1 for r in rows if r['prefecture']==p) for p in PREFS}}
 (OUT/'stats.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(stats,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
