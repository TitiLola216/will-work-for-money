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
KEYWORDS = ('customer success', 'customer service', 'inbound sales', 'technical account', 'technical support', 'client success', 'saas', 'fintech', 'ai', 'automation', 'crm', 'systems', 'operations', 'support', 'implementation', 'onboarding', 'account manager', 'customer experience', 'solutions')
REMOTE_RE = re.compile(r'\bremote\b', re.I)
US_ELIGIBLE_RE = re.compile(r'(united states|u\.?s\.?\s*(only|remote|based)|ohio|cleveland)', re.I)
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; WillWorkForMoneyJobResearch/1.1)',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://jobs.lever.co/'
}

def get_json(board):
    attempts = [
        f'https://api.lever.co/v0/postings/{board}?mode=json',
        f'https://jobs.lever.co/{board}?mode=json'
    ]
    errors = []
    for url in attempts:
        try:
            with urlopen(Request(url, headers=HEADERS), timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            errors.append(f'{error.code} {url}')
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            errors.append(f'{type(error).__name__} {url}')
    raise RuntimeError(' | '.join(errors))

def is_live(url):
    if not url:
        return False
    try:
        with urlopen(Request(url, headers=HEADERS), timeout=30) as response:
            return 200 <= response.status < 400
    except (HTTPError, URLError, TimeoutError):
        return False

def plain(value):
    return re.sub(r'<[^>]+>', ' ', value or '')

def salary(job):
    value = job.get('salaryRange')
    return value if isinstance(value, str) else (json.dumps(value, ensure_ascii=False) if value else '')

def score(title, body):
    text = f'{title} {body}'.lower()
    value = 50 + min(30, sum(word in text for word in KEYWORDS) * 5)
    if re.search(r'(customer success|technical support|implementation|onboarding|operations|crm)', text):
        value += 15
    if re.search(r'(scrum|agile|hubspot|notion|zapier|make|automation)', text):
        value += 5
    return min(value, 100)

def main():
    boards = json.loads((ROOT / 'config/lever_boards.json').read_text())['boards']
    candidates, checked, errors = [], 0, []
    for board in boards:
        try:
            jobs = get_json(board)
        except RuntimeError as error:
            errors.append(f'{board}: {error}')
            continue
        for job in jobs:
            checked += 1
            created = datetime.fromtimestamp(job.get('createdAt', 0) / 1000, UTC)
            title = job.get('text', '')
            description = plain(job.get('descriptionPlain') or job.get('description', ''))
            location = job.get('categories', {}).get('location', '')
            body = f'{description} {location}'
            apply_url = job.get('applyUrl') or job.get('hostedUrl', '')
            if created < CUTOFF or not any(word in f'{title} {body}'.lower() for word in KEYWORDS):
                continue
            if not REMOTE_RE.search(body) or not US_ELIGIBLE_RE.search(body):
                continue
            if not is_live(job.get('hostedUrl', apply_url)):
                continue
            candidates.append({'discovered_at_utc': NOW.isoformat(), 'title': title, 'company': board, 'location_work_arrangement': location or 'Remote; verify details on application page', 'salary': salary(job), 'original_posted_at_utc': created.isoformat(), 'posting_age_hours': round((NOW - created).total_seconds() / 3600, 1), 'match_score': score(title, body), 'status': 'Candidate — human experience-gap review required', 'why_candidate': 'Live direct Lever ATS page; posted within 24 hours; remote and US/Ohio/Cleveland eligibility text detected; role keyword matched.', 'biggest_gap': 'Automated workflow cannot verify the candidate’s documented employment-duration fit.', 'application_url': apply_url})
    candidates.sort(key=lambda row: (-row['match_score'], row['posting_age_hours']))
    fields = ['discovered_at_utc', 'title', 'company', 'location_work_arrangement', 'salary', 'original_posted_at_utc', 'posting_age_hours', 'match_score', 'status', 'why_candidate', 'biggest_gap', 'application_url']
    with (ROOT / 'job_tracker.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(candidates)
    report_dir = ROOT / 'reports'; report_dir.mkdir(exist_ok=True)
    lines = ['# Latest no-key ATS search report', '', f'Run time (UTC): {NOW.isoformat()}', f'Direct Lever ATS boards queried: {len(boards)}', f'Active postings evaluated: {checked}', f'Candidates passing automated checks: {len(candidates)}', '', '## Verification boundary', '', 'These are candidates, not fully verified recommendations. The workflow verifies an active direct ATS response, direct application page reachability, Lever created-at timestamp within 24 hours, a relevant keyword, and explicit remote plus US/Ohio/Cleveland eligibility language. A person must still confirm the employer, original-posting semantics, complete requirements, and the documented experience-gap hard filter before a role is recommended.', '', '## Candidates', '']
    if candidates:
        lines.extend(['| Score | Role | Employer board | Posted (UTC) | Age | Apply |', '|---:|---|---|---|---:|---|'])
        lines.extend(f"| {row['match_score']} | {row['title']} | {row['company']} | {row['original_posted_at_utc']} | {row['posting_age_hours']} h | [Apply]({row['application_url']}) |" for row in candidates)
    else:
        lines.append('No candidate passed every automated check in this run. This is not evidence that no qualifying jobs exist; it only covers the configured public Lever ATS boards.')
    if errors:
        lines.extend(['', '## Unavailable boards', '', *[f'- {item}' for item in errors]])
    (report_dir / 'latest.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

if __name__ == '__main__':
    main()
