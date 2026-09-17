#!/usr/bin/env python3
"""Check a built Jekyll site without a browser or third-party packages.

Examples:
  python3 tools/check_site.py --built _site --source .
  python3 tools/check_site.py --built ../site-project --source . --baseurl /research-portfolio

External URLs are not fetched. --original may point to the old repository to
check preservation of its publication and talk permalinks.
"""
from __future__ import annotations
import argparse
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urljoin, urlsplit

class Page(HTMLParser):
    def __init__(self, text: str):
        super().__init__(convert_charrefs=True)
        self.doctype = False
        self.lang = None
        self.h1 = 0
        self.ids = set()
        self.links = []
        self.canonicals = []
        self.descriptions = []
        self.title_text = []
        self.in_title = False
        self.text = []
        self.images = []
        self.feed(text)
    def handle_decl(self, decl):
        if decl.lower() == 'doctype html': self.doctype = True
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'html': self.lang = a.get('lang')
        if tag == 'h1': self.h1 += 1
        if a.get('id'): self.ids.add(a['id'])
        if tag == 'a' and a.get('name'): self.ids.add(a['name'])
        if tag == 'title': self.in_title = True
        if tag == 'meta' and a.get('name', '').lower() == 'description':
            self.descriptions.append(a.get('content', ''))
        if tag == 'link' and 'canonical' in a.get('rel', '').split():
            self.canonicals.append(a.get('href', ''))
        for key in ('href', 'src', 'poster', 'data', 'action'):
            if a.get(key): self.links.append((tag + ':' + key, a[key]))
        if a.get('srcset'):
            for item in a['srcset'].split(','):
                bits = item.strip().split()
                if bits: self.links.append((tag + ':srcset', bits[0]))
        if a.get('style'):
            for url in css_urls(a['style']): self.links.append(('inline-css', url))
        if tag == 'img': self.images.append(a)
    def handle_endtag(self, tag):
        if tag == 'title': self.in_title = False
    def handle_data(self, data):
        self.text.append(data)
        if self.in_title: self.title_text.append(data)

def css_urls(text):
    return [a or b or c for a, b, c in re.findall(r'url\(\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s)]*))\s*\)', text)]

def scalar(text, key, default=''):
    match = re.search(r'^' + re.escape(key) + r':\s*(.*?)\s*$', text, re.M)
    return match.group(1).strip('\"\'') if match else default

def route_for(path: Path):
    route = '/' + path.as_posix()
    return route[:-10] if route.endswith('index.html') else route

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--built', type=Path, required=True)
    ap.add_argument('--source', type=Path, default=Path('.'))
    ap.add_argument('--baseurl', default='')
    ap.add_argument('--site-url', default='https://nairarshad.github.io')
    ap.add_argument('--original', type=Path)
    ap.add_argument('--json', type=Path)
    ap.add_argument('--expected-publications', type=int, default=19)
    ap.add_argument('--expected-talks', type=int, default=29)
    ap.add_argument('--expected-research', type=int, default=4)
    args = ap.parse_args()
    root = args.built.resolve()
    source = args.source.resolve()
    base = '/' + args.baseurl.strip('/') if args.baseurl.strip('/') else ''
    origin = args.site_url.rstrip('/')
    host = urlsplit(origin).netloc
    errors = []
    warnings = []
    def error(message): errors.append(message)
    if not root.is_dir():
        print('ERROR: built directory does not exist:', root)
        return 1
    pages = {}
    for path in sorted(root.rglob('*.html')):
        rel = path.relative_to(root)
        raw = path.read_text(encoding='utf-8')
        page = Page(raw)
        pages[path] = page
        name = rel.as_posix()
        if not page.doctype: error(f'{name}: missing HTML5 doctype')
        if not page.lang: error(f'{name}: missing document language')
        if page.h1 != 1: error(f'{name}: expected one H1, found {page.h1}')
        if not ''.join(page.title_text).strip(): error(f'{name}: missing title')
        if len(page.descriptions) != 1 or not page.descriptions[0].strip():
            error(f'{name}: expected one nonempty meta description')
        expected = origin + base + route_for(rel)
        if page.canonicals != [expected]:
            error(f'{name}: canonical {page.canonicals!r}; expected {expected!r}')
        if re.search(r'\{\{|\{%|%\}', raw): error(f'{name}: unresolved Liquid syntax')
        for img in page.images:
            if 'alt' not in img: error(f'{name}: image missing alt attribute')
    if not pages: error('No generated HTML pages found')

    checked_links = 0
    fragments = 0
    def check_url(url, from_path, from_url, kind):
        nonlocal checked_links, fragments
        if url.startswith(('data:', 'mailto:', 'tel:', 'javascript:', 'blob:')): return
        joined = urlsplit(urljoin(from_url, url))
        if joined.scheme not in ('http', 'https') or joined.netloc != host: return
        checked_links += 1
        public_path = unquote(joined.path)
        label = from_path.relative_to(root).as_posix()
        if base and not (public_path == base or public_path.startswith(base + '/')):
            error(f'{label}: local {kind} escapes baseurl {base}: {url}')
            return
        internal = public_path[len(base):] if base else public_path
        candidate = (root / internal.lstrip('/')).resolve()
        if candidate != root and root not in candidate.parents:
            error(f'{label}: {kind} escapes built root: {url}')
            return
        if candidate.is_dir(): candidate /= 'index.html'
        if not candidate.is_file():
            error(f'{label}: missing local {kind}: {url}')
            return
        if joined.fragment and candidate.suffix == '.html':
            fragments += 1
            target = pages.get(candidate)
            fragment = unquote(joined.fragment)
            if fragment and target and fragment not in target.ids:
                error(f'{label}: missing fragment {url}')
    for path, page in pages.items():
        here = origin + base + route_for(path.relative_to(root))
        for kind, url in page.links: check_url(url, path, here, kind)
    for path in root.rglob('*.css'):
        here = origin + base + '/' + path.relative_to(root).as_posix()
        for url in css_urls(path.read_text(encoding='utf-8')):
            check_url(url, path, here, 'CSS asset')

    counts = {}
    for folder, expected in (('_publications', args.expected_publications),
                             ('_talks', args.expected_talks),
                             ('_research', args.expected_research)):
        files = list((source / folder).glob('*.md'))
        counts[folder] = len(files)
        if len(files) != expected:
            error(f'{folder}: expected {expected} Markdown records, found {len(files)}')
        for file in files:
            body = file.read_text(encoding='utf-8')
            route = scalar(body, 'permalink') or f'/{folder[1:]}/{file.stem}/'
            path = root / route.strip('/')
            if path.is_dir(): path /= 'index.html'
            if not path.is_file(): error(f'{file.name}: missing generated collection route {route}')

    # Ensure the requested public presentation remains intact. These checks are
    # targeted text/filename guards, not a claim of semantic or image recognition.
    image_files = [p for p in root.rglob('*') if p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.gif')]
    for file in image_files:
        if file.name.lower() == 'nair.png' or re.search(r'arshad[-_]nair', file.name, re.I):
            error(f'Arshad portrait asset remains: {file.relative_to(root)}')
    sensitive = re.compile(r'\b(?:immigration|visa|spouse|husband|wife|married)\b|Sagarika\s+Basak|\bH[ -]?[14]B?\b|\bfamily circumstances\b', re.I)
    current_role = re.compile(r'\b(?:currently|presently|I am|I work|I serve)\b[^.\n]{0,110}\b(?:Ramanujan|ISRO|Vikram Sarabhai)\b|(?:Ramanujan|ISRO|Vikram Sarabhai)[^.\n]{0,80}\b(?:present|current appointment)\b', re.I)
    for path, page in pages.items():
        visible = ' '.join(page.text)
        if sensitive.search(visible): error(f'{path.relative_to(root)}: private family/immigration text guard matched')
        if current_role.search(visible): error(f'{path.relative_to(root)}: possibly current ISRO/Fellow role language')
        for img in page.images:
            if re.search(r'portrait|headshot', img.get('alt', ''), re.I) and re.search(r'Arshad', img.get('alt', ''), re.I):
                error(f'{path.relative_to(root)}: Arshad portrait/headshot alt text remains')
    config = (source / '_config.yml').read_text(encoding='utf-8')
    if re.search(r'Ramanujan|ISRO|Vikram Sarabhai', scalar(config, 'role') + scalar(config, 'affiliation'), re.I):
        error('_config.yml: current-role/affiliation field still names the former appointment')
    cv = source / 'files/Arshad_Nair_CV.tex'
    if cv.exists():
        text = cv.read_text(encoding='utf-8')
        if sensitive.search(text): error('CV source: private family/immigration text guard matched')
        for line in text.splitlines():
            if re.search(r'Ramanujan|ISRO', line, re.I) and re.search(r'\bpresent\b', line, re.I):
                error('CV source: former appointment still marked present')

    retained = Counter()
    if args.original:
        for folder in ('_publications', '_talks'):
            for file in (args.original / folder).glob('*.md'):
                old_route = scalar(file.read_text(encoding='utf-8'), 'permalink')
                if not old_route: continue
                target = root / old_route.strip('/')
                if target.is_dir(): target /= 'index.html'
                if not target.is_file(): error(f'Legacy route missing: {old_route}')
                else: retained[folder] += 1
    for excluded in ('README.md', 'EDITING.md', 'UPLOAD_TO_GITHUB.md', 'VALIDATION.md', 'ASSET_NOTES.md', 'tools', 'templates', '_templates', 'Gemfile', 'Gemfile.lock'):
        if (root / excluded).exists(): error(f'Editing/build-only file was published: {excluded}')
    if (source / '.nojekyll').exists(): error('.nojekyll would disable Markdown/Jekyll processing')
    for folder in ('_plugins', 'node_modules', '_site'):
        if (source / folder).exists(): warnings.append(f'Source includes {folder}; review before upload')
    if not (source / 'Gemfile').exists(): error('Gemfile missing')

    result = {
        'status': 'PASS' if not errors else 'FAIL',
        'baseurl': base, 'html_pages': len(pages), 'local_references_checked': checked_links,
        'fragment_references_checked': fragments, 'source_records': counts,
        'retained_legacy_routes': dict(retained), 'errors': sorted(set(errors)), 'warnings': warnings,
        'limitations': ['No browser rendering or interaction test performed.',
                        'External URLs were not fetched.',
                        'Text and asset checks are targeted guards, not comprehensive semantic/privacy analysis.'],
    }
    print(json.dumps(result, indent=2))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return 1 if errors else 0

if __name__ == '__main__':
    sys.exit(main())
