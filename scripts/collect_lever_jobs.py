import csv,json,re,xml.etree.ElementTree as ET
from datetime import UTC,datetime,timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

ROOT=Path(__file__).resolve().parents[1]; NOW=datetime.now(UTC); CUT=NOW-timedelta(hours=24)
H={'User-Agent':'Mozilla/5.0 (compatible; WillWorkForMoneyJobResearch/2.0)','Accept':'application/json,application/rss+xml,text/xml,*/*'}
TARGET=('customer success','client success','customer support','technical support','support specialist','support analyst','customer experience','customer operations','implementation','onboarding','technical account','customer account','customer service','crm','operations')
BAD=('product designer','ux designer','ui designer','software engineer','developer','data scientist','network security','security engineer','cloud engineer','devops','recruiter','vice president','chief ')

def get(url):
    with urlopen(Request(url,headers=H),timeout=30) as r:return r.read()
def ok(title):
    t=title.lower(); return any(x in t for x in TARGET) and not any(x in t for x in BAD)
def dt(v):
    try:return parsedate_to_datetime(v).astimezone(UTC)
    except:return None
def row(source,title,company,posted,url,location='',salary='',verified=False):
    if not ok(title):return None
    age=round((NOW-posted).total_seconds()/3600,1) if posted else ''
    status='Apply now — direct ATS verification passed' if verified else 'Review today — live source lead; confirm direct employer application page'
    return {'source':source,'title':title,'company':company or 'Not provided','location_work_arrangement':location or 'Remote; verify US/Ohio eligibility','salary':salary,'posted_at_utc':posted.isoformat() if posted else 'Source did not provide a reliable original posting time','posting_age_hours':age,'match_score':90 if verified else 70,'status':status,'why_candidate':'Target role title matches customer success, support, implementation, onboarding, CRM, or operations.','biggest_gap':'Confirm employer-direct application page, Ohio/US eligibility, and stated experience requirements before applying.','application_url':url}
def main():
    out=[]; errors=[]
    boards=json.loads((ROOT/'config/lever_boards.json').read_text())['boards']
    for b in boards:
      try:
       jobs=json.loads(get(f'https://api.lever.co/v0/postings/{b}?mode=json'))
       for j in jobs:
        posted=datetime.fromtimestamp(j.get('createdAt',0)/1000,UTC); title=j.get('text',''); body=re.sub('<[^>]+>',' ',j.get('descriptionPlain') or j.get('description','')); loc=j.get('categories',{}).get('location','')
        if posted>=CUT and 'remote' in (body+' '+loc).lower() and re.search(r'united states|u\.?s\.?|ohio|cleveland',body+' '+loc,re.I):
          x=row('Lever direct ATS',title,b,posted,j.get('applyUrl') or j.get('hostedUrl',''),loc,j.get('salaryRange',''),True)
          if x:out.append(x)
      except Exception as e:errors.append(f'Lever {b}: {type(e).__name__}')
    try:
      for item in json.loads(get('https://remoteok.com/api')):
       if not isinstance(item,dict) or not item.get('position'):continue
       posted=dt(item.get('date',''))
       if posted and posted>=CUT:
        x=row('Remote OK',item['position'],item.get('company',''),posted,item.get('url',''),item.get('location','Remote'),item.get('salary',''))
        if x:out.append(x)
    except Exception as e:errors.append(f'Remote OK: {type(e).__name__}')
    try:
      root=ET.fromstring(get('https://weworkremotely.com/categories/remote-customer-support-jobs.rss'))
      for i in root.findall('.//item'):
       posted=dt(i.findtext('pubDate','')); title=i.findtext('title',''); link=i.findtext('link','')
       if posted and posted>=CUT:
        x=row('We Work Remotely',title,title.split(':')[0] if ':' in title else '',posted,link,'Remote')
        if x:out.append(x)
    except Exception as e:errors.append(f'We Work Remotely: {type(e).__name__}')
    seen=set();out=[x for x in sorted(out,key=lambda x:(-x['match_score'],x['posting_age_hours'] if x['posting_age_hours']!='' else 999)) if not ((x['title'].lower(),x['company'].lower()) in seen or seen.add((x['title'].lower(),x['company'].lower())))]
    fields=list(out[0]) if out else ['source','title','company','location_work_arrangement','salary','posted_at_utc','posting_age_hours','match_score','status','why_candidate','biggest_gap','application_url']
    with (ROOT/'job_tracker.csv').open('w',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
    lines=['# Latest lead-producing multi-source report','',f'Run time (UTC): {NOW.isoformat()}',f'Leads returned: {len(out)}','', '## Apply now — direct ATS verified','']
    for x in out:
      if x['match_score']==90:lines.append(f"- [{x['title']}]({x['application_url']}) — {x['company']} — {x['posting_age_hours']} hours old")
    lines+=['','## Review today — live discovery leads','']
    for x in out:
      if x['match_score']!=90:lines.append(f"- [{x['title']}]({x['application_url']}) — {x['company']} — {x['source']} — {x['posting_age_hours']} hours old")
    if not out:lines.append('No lead was returned by the configured sources in this 24-hour window.')
    if errors:lines+=['','## Source errors','',*[f'- {e}' for e in errors]]
    (ROOT/'reports'/'latest.md').write_text('\n'.join(lines)+'\n')
if __name__=='__main__':main()
