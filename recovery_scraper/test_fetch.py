import requests, time
url='https://www.zennichi.net/hp/kanto_kaiin/pref.asp?p=13&pg=1&s='
headers={
 'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0 Safari/537.36',
 'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
 'Accept-Language':'ja-JP,ja;q=0.9,en;q=0.7',
 'Connection':'close',
}
for i in range(3):
 t=time.time()
 try:
  r=requests.get(url,headers=headers,timeout=60)
  print(i, r.status_code, len(r.content), round(time.time()-t,2), r.url, r.headers.get('content-type'))
  print(r.content[:200])
 except Exception as e:
  print(i, type(e).__name__, str(e), round(time.time()-t,2))
 time.sleep(3)
