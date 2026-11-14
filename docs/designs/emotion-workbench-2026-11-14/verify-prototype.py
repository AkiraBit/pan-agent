"""Artifact QA. Requires playwright, Chrome and jsonschema; no production services.

Run a static server for this directory, then:
  python3 verify-prototype.py --url http://127.0.0.1:8767/
"""
import argparse
import copy
import json
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://127.0.0.1:8767/')
args = parser.parse_args()
checks = []
errors = []
requests = []


def record(name, fn):
    try:
        fn()
        checks.append({'name': name, 'passed': True})
    except Exception as exc:
        checks.append({'name': name, 'passed': False, 'error': str(exc)})


def ensure(value, message):
    if not value:
        raise AssertionError(message)


def references(d):
    ids = {key: {x['id'] for x in d[key]} for key in ['stocks', 'evidence', 'conditions', 'scenarios']}
    for key in ids:
        ensure(len(ids[key]) == len(d[key]), f'duplicate {key} ID')
    for obj in d['stocks'] + d['conditions']:
        ensure(set(obj['evidence']) <= ids['evidence'], 'dangling evidence reference')
    for c in d['conditions']:
        ensure(c['subject'] is None or c['subject'] in ids['stocks'], 'unknown condition subject')
    for scenario in d['scenarios']:
        ensure(set(scenario['requires']) <= ids['conditions'], 'unknown scenario condition')
    for constraint in d['constraints']:
        ensure(constraint['evidence_id'] in ids['evidence'], 'unknown constraint evidence')
    content = d['content']
    for step in content['chain']:
        ensure(step['condition_id'] in ids['conditions'], 'unknown chain condition')
    for branch in content['branches']:
        ensure(set(branch['members']) <= ids['stocks'], 'unknown branch member')
    nodes = {n['symbol'] for n in content['graph']['nodes']}
    ensure(nodes <= ids['stocks'], 'unknown graph node')
    for edge in content['graph']['edges']:
        ensure(edge['from'] in nodes and edge['to'] in nodes, 'unknown edge endpoint')
        ensure(edge['evidence_id'] in ids['evidence'], 'unknown edge evidence')
    for stock in d['stocks']:
        ensure(not stock['bars'] or len(stock['bars']) == len(content['history_dates']), 'chart dates mismatch')
    ensure(datetime.fromisoformat(d['as_of']) <= datetime.fromisoformat(d['knowledge_cutoff']), 'future market data')
    if d['mode'] in ['relay', 'retreat']:
        ensure(d['data_status'] == 'simulated' and all(s.get('simulated') for s in d['stocks']), 'unmarked simulation')
    if d['mode'] == 'stale':
        ensure(all(c['state'] == 'unknown' for c in d['conditions']), 'missing data treated as failure')


schema = json.loads((ROOT / 'prototype.schema.json').read_text())
validator = Draft202012Validator(schema, format_checker=FormatChecker())
record('JSON Schema Draft 2020-12 is valid', lambda: validator.check_schema(schema))
fixtures = {}
for mode in ['weekend', 'relay', 'retreat', 'stale']:
    filename = 'example-output.json' if mode == 'weekend' else f'snapshot-{mode}.json'
    fixtures[mode] = json.loads((ROOT / filename).read_text())
    record(f'{mode}: schema, IDs, references, dates and data state', lambda m=mode: (validator.validate(fixtures[m]), references(fixtures[m])))


def rejects_bad_contract():
    bad = copy.deepcopy(fixtures['weekend'])
    bad['pages']['overview'][0]['kind'] = 'arbitrary_html'
    ensure(not validator.is_valid(bad), 'unsupported module accepted')
    bad = copy.deepcopy(fixtures['weekend'])
    bad['evidence'][0]['url'] = 'javascript:alert(1)'
    ensure(not validator.is_valid(bad), 'unsafe URL accepted')
    bad = copy.deepcopy(fixtures['weekend'])
    bad['conditions'][0]['evidence'] = ['not-an-evidence-id']
    try:
        references(bad)
    except AssertionError:
        return
    raise AssertionError('dangling evidence reference accepted')


record('Reject unknown modules, unsafe URLs and dangling evidence references', rejects_bad_contract)

PAGES = ['overview', 'cycle', 'playbook', 'stock', 'evidence', 'review', 'agent']
(ROOT / 'screenshots').mkdir(exist_ok=True)
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome')
    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1, reduced_motion='reduce')
    page = context.new_page()
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('request', lambda r: requests.append(r.url))
    page.goto(args.url, wait_until='networkidle')

    def nav(name):
        page.locator(f'.rail-nav [data-value="{name}"]').click()
        page.wait_for_function('(name) => window.__prototype.state.page === name', arg=name)
        page.evaluate('window.scrollTo(0,0)')

    def mode(name):
        page.select_option('#mode-select', name)
        page.wait_for_function('(name) => window.__prototype.getSnapshot().mode === name', arg=name)
        page.evaluate('document.getElementById("toast").classList.remove("show")')

    def layout(name):
        ensure(page.locator('h1').is_visible(), f'{name}: no page title')
        ensure(not page.evaluate('document.documentElement.scrollWidth > window.innerWidth'), f'{name}: page overflow')
        ensure(page.locator('.content-grid > div').count() > 0, f'{name}: no modules')

    for m in fixtures:
        mode(m)
        record(f'{m}: exported fixture equals renderer input', lambda m=m: ensure(page.evaluate('window.__prototype.getSnapshot()') == fixtures[m], 'fixture drift'))
        for name in PAGES:
            nav(name)
            record(f'Desktop {m}/{name}: renders without horizontal page overflow', lambda n=name: layout(n))

    def scene_modules():
        nav('overview')
        mode('relay')
        ensure(page.get_by_text('本次新增变化', exact=True).count() == 1, 'missing delta module')
        mode('retreat')
        ensure(page.get_by_text('推演提醒：强势尚未扩散', exact=True).count() == 1, 'missing risk module')
        mode('stale')
        ensure(page.get_by_text('数据降级 · 依赖行情的条件全部暂停', exact=True).count() == 1, 'missing data gap')
        ensure(page.locator('.metrics').count() == 0, 'stale summary metrics remain')
    record('Snapshot changes insert/remove modules and preserve unknown state', scene_modules)
    mode('weekend')

    def stock_navigation():
        nav('overview')
        page.locator('tr[data-value="002578.SZ"]').focus()
        page.keyboard.press('Enter')
        ensure(page.locator('h2').filter(has_text='闽发铝业').count() == 1, 'stock row keyboard navigation')
        ensure(page.get_by_text('周一正常涨停价测算为 5.98 元，仍低于 6.04 元', exact=True).count() == 1, 'missing independent constraint')
        page.locator('.stock-selector [data-value="000678.SZ"]').click()
        ensure(page.get_by_text('完整历史序列尚未收录', exact=True).count() == 1, 'missing history fabricated')
        nav('cycle')
        page.locator('[data-action="branch"][data-value="光伏"]').click()
        ensure(page.locator('g.map-node[opacity="1"]').count() == 1, 'branch member filter incorrect')
        page.locator('g[data-value="002578.SZ"]').focus()
        page.keyboard.press('Enter')
        ensure(page.locator('h2').filter(has_text='闽发铝业').count() == 1, 'map keyboard navigation')
    record('Stock row, map keyboard navigation, branch filtering and missing history', stock_navigation)

    def playbook_interaction():
        nav('playbook')
        page.locator('[data-action="scenario"][data-value="rotate"]').click()
        ensure(page.get_by_text('传媒独立走强 · 此情景重点', exact=True).count() == 1, 'scenario body did not update')
        page.locator('[data-action="phase"][data-value="opening"]').click()
        ensure(page.get_by_text('检验第一次回落', exact=True).count() == 1, 'timeline did not change')
        page.locator('[data-action="scenario-detail"]').click()
        ensure(page.locator('#detail-dialog').is_visible(), 'scenario dialog not visible')
        ensure(page.locator('#detail-dialog').get_by_text('失效条件', exact=True).count() == 1, 'missing invalidation')
        page.keyboard.press('Escape')
        ensure(not page.locator('#detail-dialog').is_visible(), 'escape does not close dialog')
    record('Scenario selection, timeline selection, invalidation dialog and Escape', playbook_interaction)

    def evidence_and_context():
        nav('evidence')
        page.locator('[data-action="evidence-filter"][data-value="待核验"]').click()
        ensure(page.locator('.evidence-item').count() == 3, 'wrong unresolved constraint count')
        page.locator('[data-action="evidence"][data-value="e-window"]').click()
        ensure(page.locator('#detail-dialog a').get_attribute('rel') == 'noopener noreferrer', 'unsafe external link')
        page.keyboard.press('Escape')
        page.locator('.page-actions [data-action="correction"]').click()
        payload = '<img src=x onerror="window.__xss=true">需要核验原文'
        page.fill('#correction-input', payload)
        page.locator('[data-action="save-correction"]').click()
        ensure(page.locator('.evidence-item').count() == 4, 'new user context not saved')
        ensure(page.evaluate('window.__xss') is None, 'context executed as HTML')
        snapshot = page.evaluate('window.__prototype.getSnapshot()')
        ensure(snapshot['evidence'][-1]['status'] == '待核验', 'user input upgraded to fact')
        ensure(snapshot['title'] == fixtures['weekend']['title'], 'unverified input changed conclusion')
        page.reload(wait_until='networkidle')
        ensure(len(page.evaluate('window.__prototype.state.notes')) == 1, 'context did not persist locally')
        page.evaluate('localStorage.removeItem("pan-emotion-prototype-notes")')
        page.reload(wait_until='networkidle')
    record('Evidence provenance, unresolved filter, escaped user context and local persistence', evidence_and_context)

    def export_and_controls():
        nav('agent')
        page.locator('[data-action="raw"]').last.click()
        with page.expect_download() as event:
            page.locator('#detail-dialog [data-action="export"]').click()
        download = event.value
        output = json.loads(Path(download.path()).read_text())
        validator.validate(output)
        ensure(output == fixtures['weekend'], 'download differs from snapshot')
        page.keyboard.press('Escape')
        page.locator('[data-action="monitor"]').click()
        ensure(page.evaluate('window.__prototype.state.monitor') is True, 'demo toggle failed')
        page.locator('[data-action="monitor"]').click()
        page.locator('[data-action="run"]').click()
        page.wait_for_timeout(1500)
        ensure('未调用真实模型' in page.locator('#toast').inner_text(), 'replay not labeled')
    record('JSON export, explicit demo monitor and replay controls', export_and_controls)

    page.goto(args.url, wait_until='networkidle')
    for i, name in enumerate(PAGES, 1):
        nav(name)
        page.screenshot(path=str(ROOT / 'screenshots' / f'{i:02d}-{name}.png'), full_page=True)
    page.locator('.rail-nav [data-value="stock"]').click()
    page.locator('.stock-selector [data-value="002578.SZ"]').click()
    page.screenshot(path=str(ROOT / 'screenshots' / '08-stock-minfa.png'), full_page=True)
    nav('overview')
    for number, m in [(9, 'relay'), (10, 'retreat'), (11, 'stale')]:
        mode(m)
        page.screenshot(path=str(ROOT / 'screenshots' / f'{number:02d}-{m}.png'), full_page=True)
    mode('weekend')
    page.locator('[data-action="theme"]').click()
    record('Light theme state', lambda: ensure(page.locator('html').get_attribute('class') == 'light', 'theme did not switch'))
    page.screenshot(path=str(ROOT / 'screenshots' / '14-light-overview.png'), full_page=True)
    page.locator('[data-action="theme"]').click()
    page.set_viewport_size({'width': 390, 'height': 844})
    for name in PAGES:
        nav(name)
        record(f'Mobile 390px/{name}: renders without horizontal page overflow', lambda n=name: layout(n))
        if name in ['overview', 'playbook', 'stock']:
            number = {'overview': 12, 'playbook': 13, 'stock': 15}[name]
            page.screenshot(path=str(ROOT / 'screenshots' / f'{number:02d}-mobile-{name}.png'), full_page=True)
    page.set_viewport_size({'width': 320, 'height': 740})
    for name in PAGES:
        nav(name)
        record(f'Small mobile 320px/{name}: renders without horizontal page overflow', lambda n=name: layout(n))
    record('No browser JavaScript exceptions', lambda: ensure(not errors, repr(errors)))
    from urllib.parse import urlparse
    allowed = urlparse(args.url).netloc
    external = [u for u in requests if urlparse(u).scheme in ['http', 'https'] and urlparse(u).netloc != allowed]
    record('Prototype makes no model, market, account or third-party requests', lambda: ensure(not external, repr(external)))
    browser.close()

report = {'scope':'Design artifact only; not production, live trading, agent reasoning or market feed validation', 'browser':'Installed Google Chrome through Playwright', 'checked_at':datetime.now().astimezone().isoformat(), 'checks':checks,'passed':sum(c['passed'] for c in checks),'failed':sum(not c['passed'] for c in checks),'browser_errors':errors}
(ROOT / 'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'passed':report['passed'],'failed':report['failed'],'failures':[c for c in checks if not c['passed']]},ensure_ascii=False,indent=2))
raise SystemExit(1 if report['failed'] else 0)
