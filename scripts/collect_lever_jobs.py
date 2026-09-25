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
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; WillWorkForMoneyJobResearch/1.2)', 'Accept': 'application/json, text/plain, */*', 'Referer': 'https://jobs.lever.co/'}
REMOTE_RE = re.compile(r'\bremote\b', re.I)
US_ELIGIBLE_RE = re.compile(r'(united states|u\.?s\.?\s*(only|remote|based)|ohio|cleveland)', re.I)
YEARS_RE = re.compile(r'\b(\d{1,2})\s*\+?\s*years?\b', re.I)

def get_json(board):
    attempts = [f'https://api.lever.co/v0/postings/{board}?mode=json', f'https://jobs.lever.co/{board}?mode=json']
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

def contains_any(text, patterns):
    return [pattern for pattern in patterns if pattern in text]

def salary(job):
    value = job.get('salaryRange')
    return value if isinstance(value, str) else (json.dumps(value, ensure_ascii=False) if value else '')

def required_years(text):
    values = [int(value) for value in YEARS_RE.findall(text)]
    return max(values) if values else None

def main():
    profile = json.loads((ROOT / 'config/candidate_profile.json').read_text())
    boards = json.loads((ROOT / 'config/lever_boards.json').read_text())['boards']
    candidates, checked, errors, excluded = [], 0, [], 0
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
            title_lower = title.lower()
            description = plain(job.get('descriptionPlain') or job.get('description', ''))
            location = job.get('categories', {}).get('location', '')
            body = f'{description} {location}'
            body_lower = body.lower()
            apply_url = job.get('applyUrl') or job.get('hostedUrl', '')
            if created < CUTOFF or not REMOTE_RE.search(body) or not US_ELIGIBLE_RE.search(body):
                continue
            title_hits = contains_any(title_lower, profile['target_title_patterns'])
            excluded_hits = contains_any(title_lower, profile['excluded_title_patterns']) + contains_any(body_lower, profile['excluded_requirement_patterns'])
            strength_hits = contains_any(f'{title_lower} {body_lower}', profile['strength_patterns'])
            if excluded_hits or not title_hits or not strength_hits or not is_live(job.get('hostedUrl', apply_url)):
                excluded += 1
                continue
            years = required_years(body_lower)
            age_hours = round((NOW - created).total_seconds() / 3600, 1)
            score = min(100, 65 + min(20, len(title_hits) * 10) + min(15, len(strength_hits) * 3))
            experience_note = f'Stated requirement includes up to {years} years; compare it against a dated resume before recommending.' if years else 'No numeric experience requirement was detected; review the full requirements before recommending.'
            candidates.append({'discovered_at_utc': NOW.isoformat(), 'title': title, 'company': board, 'location_work_arrangement': location or 'Remote; verify details on application page', 'salary': salary(job), 'original_posted_at_utc': created.isoformat(), 'posting_age_hours': age_hours, 'match_score': score, 'status': 'Candidate — requirement and experience-gap review required', 'why_candidate': f"Target title match: {', '.join(title_hits)}. Documented-strength signals: {', '.join(strength_hits[:5])}.", 'biggest_gap': experience_note, 'application_url': apply_url})
    candidates.sort(key=lambda row: (-row['match_score'], row['posting_age_hours']))
    fields = ['discovered_at_utc', 'title', 'company', 'location_work_arrangement', 'salary', 'original_posted_at_utc', 'posting_age_hours', 'match_score', 'status', 'why_candidate', 'biggest_gap', 'application_url']
    with (ROOT / 'job_tracker.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(candidates)
    report_dir = ROOT / 'reports'; report_dir.mkdir(exist_ok=True)
    lines = ['# Latest experience-aligned ATS search report', '', f'Run time (UTC): {NOW.isoformat()}', f'Direct Lever ATS boards queried: {len(boards)}', f'Active postings evaluated: {checked}', f'Excluded as out-of-lane: {excluded}', f'Candidates passing experience-aligned automated checks: {len(candidates)}', '', '## Verification boundary', '', profile['experience_rule'], '', '## Candidates', '']
    if candidates:
        lines.extend(['| Score | Role | Employer board | Posted (UTC) | Age | Apply |', '|---:|---|---|---|---:|---|'])
        lines.extend(f"| {row['match_score']} | {row['title']} | {row['company']} | {row['original_posted_at_utc']} | {row['posting_age_hours']} h | [Apply]({row['application_url']}) |" for row in candidates)
    else:
        lines.append('No role passed the experience-aligned automated checks in this run. This does not prove that no fitting job exists; it only covers the configured direct Lever ATS boards.')
    if errors:
        lines.extend(['', '## Unavailable boards', '', *[f'- {item}' for item in errors]])
    (report_dir / 'latest.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

if __name__ == '__main__':
    main()
