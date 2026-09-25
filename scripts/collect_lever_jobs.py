import csv
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(UTC)
CUTOFF = NOW - timedelta(hours=24)
KEYWORDS = (
    'customer success', 'customer service', 'inbound sales',
    'technical account', 'technical support', 'client success',
    'saas', 'fintech', 'ai', 'automation', 'crm', 'systems',
    'operations', 'support', 'implementation', 'onboarding',
    'account manager', 'customer experience', 'solutions'
)
REMOTE_RE = re.compile(r'\bremote\b', re.I)
US_ELIGIBLE_RE = re.compile(r'(united states|u\.?s\.?\s*(only|remote|based)|ohio|cleveland)', re.I)

def get_json(url):
    request = Request(url, headers={'User-Agent': 'WillWorkForMoneyJobResearch/1.0'})
    with urlopen(request, timeout=20) as response:
        return json.load(response)

def is_live(url):
    if not url:
        return False
    request = Request(url, headers={'User-Agent': 'WillWorkForMoneyJobResearch/1.0'})
    try:
        with urlopen(request, timeout=20) as response:
            return 200 <= response.status < 400
    except (HTTPError, URLError, TimeoutError):
        return False

def text_from(value):
    return re.sub(r'<[^>]+>', ' ', value or '')

def money(job):
    salary = job.get('salaryRange')
    if not salary:
        return ''
    if isinstance(salary, str):
        return salary
    return json.dumps(salary, ensure_ascii=False)

def score(title, body):
    text = f'{title} {body}'.lower()
    score = 50
    score += min(30, sum(word in text for word in KEYWORDS) * 5)
    if re.search(r'(customer success|technical support|implementation|onboarding|operations|crm)', text):
        score += 15
    if re.search(r'(scrum|agile|hubspot|notion|zapier|make|automation)', text):
        score += 5
    return min(score, 100)

def main():
    boards = json.loads((ROOT / 'config/lever_boards.json').read_text())['boards']
    candidates, checked, errors = [], 0, []
    for board in boards:
        try:
            jobs = get_json(f'https://api.lever.co/v0/postings/{board}?mode=json')
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            errors.append(f'{board}: {type(error).__name__}')
            continue
        for job in jobs:
            checked += 1
            created = datetime.fromtimestamp(job.get('createdAt', 0) / 1000, UTC)
            title = job.get('text', '')
            description = text_from(job.get('descriptionPlain') or job.get('description', ''))
            location = job.get('categories', {}).get('location', '')
            body = f'{description} {location}'
            apply_url = job.get('applyUrl') or job.get('hostedUrl', '')
            if created < CUTOFF:
                continue
            if not any(word in f'{title} {body}'.lower() for word in KEYWORDS):
                continue
            if not REMOTE_RE.search(body) or not US_ELIGIBLE_RE.search(body):
                continue
            if not is_live(job.get('hostedUrl', apply_url)):
                continue
            age_hours = round((NOW - created).total_seconds() / 3600, 1)
            candidates.append({
                'discovered_at_utc': NOW.isoformat(),
                'title': title,
                'company': board,
                'location_work_arrangement': location or 'Remote; verify details on application page',
                'salary': money(job),
                'original_posted_at_utc': created.isoformat(),
                'posting_age_hours': age_hours,
                'match_score': score(title, body),
                'status': 'Candidate — human experience-gap review required',
                'why_candidate': 'Live direct Lever ATS page; posted within 24 hours; remote and US/Ohio/Cleveland eligibility text detected; role keyword matched.',
                'biggest_gap': 'Automated workflow cannot verify the candidate’s documented employment-duration fit.',
                'application_url': apply_url
            })
    candidates.sort(key=lambda row: (-row['match_score'], row['posting_age_hours']))
    tracker = ROOT / 'job_tracker.csv'
    fields = ['discovered_at_utc', 'title', 'company', 'location_work_arrangement', 'salary', 'original_posted_at_utc', 'posting_age_hours', 'match_score', 'status', 'why_candidate', 'biggest_gap', 'application_url']
    with tracker.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(candidates)
    report_dir = ROOT / 'reports'
    report_dir.mkdir(exist_ok=True)
    lines = [
        '# Latest no-key ATS search report',
        '',
        f'Run time (UTC): {NOW.isoformat()}',
        f'Direct Lever ATS boards queried: {len(boards)}',
        f'Active postings evaluated: {checked}',
        f'Candidates passing automated checks: {len(candidates)}',
        '',
        '## Verification boundary',
        '',
        'These are candidates, not fully verified recommendations. The workflow verifies an active direct ATS response, direct application page reachability, Lever created-at timestamp within 24 hours, a relevant keyword, and explicit remote plus US/Ohio/Cleveland eligibility language. A person must still confirm the employer, original-posting semantics, complete requirements, and the documented experience-gap hard filter before a role is recommended.',
        '',
        '## Candidates',
        ''
    ]
    if candidates:
        lines.extend(['| Score | Role | Employer board | Posted (UTC) | Age | Apply |', '|---:|---|---|---|---:|---|'])
        for row in candidates:
            lines.append(f"| {row['match_score']} | {row['title']} | {row['company']} | {row['original_posted_at_utc']} | {row['posting_age_hours']} h | [Apply]({row['application_url']}) |")
    else:
        lines.append('No candidate passed every automated check in this run. This is not evidence that no qualifying jobs exist; it only covers the configured public Lever ATS boards.')
    if errors:
        lines.extend(['', '## Unavailable boards', '', *[f'- {item}' for item in errors]])
    (report_dir / 'latest.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

if __name__ == '__main__':
    main()
