#!/usr/bin/env python3
"""Portable, offline sentiment report renderer. Python standard library only."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from html import escape
import json
import math
from pathlib import Path

STAGES = {'ice': '低迷 / 冰点', 'repair': '修复', 'expansion': '发酵 / 扩张',
          'heat': '高热', 'divergence': '分歧', 'retreat': '退潮'}
DIRECTIONS = {'improving': '改善', 'stable': '稳定', 'deteriorating': '恶化', 'mixed': '分化', 'insufficient': '数据不足'}
STATUSES = {'candidate': '候选判断', 'supported': '支持较充分', 'conflicted': '证据冲突', 'insufficient': '无法验证',
            'waiting': '等待收盘', 'met': '观察条件成立', 'not_met': '观察条件未成立', 'invalidated': '反证条件成立',
            'expired': '错过验证窗口', 'review_required': '需要人工复核', 'observed': '直接观察', 'proxy': '代理口径', 'missing': '缺失'}
METRICS = {'positive_ratio': '上涨占比', 'median': '涨幅中位数（%）', 'p10': '收益第10分位（%）', 'feedback_mean': '前日强势队列平均反馈（%）'}
REASONS = {'window_not_complete': '目标交易日尚未收盘', 'missed_session': '缺少目标交易日快照，不能用后一天代替',
           'qualitative_condition': '原条件为文字，程序不能自动判定', 'coverage_or_universe_changed': '覆盖不完整或比较股票池变化',
           'metric_missing': '所需指标缺失', 'evaluated': '按登记时冻结的条件计算', 'registration_after_observation': '登记时间晚于本次观察，不能回填验证'}


def _value(facts, metric):
    metrics = facts.get('metrics', {})
    if metric == 'feedback_mean':
        feedback = metrics.get('feedback', {})
        value = feedback.get('mean_change_pct') if feedback.get('status') == 'proxy' and not feedback.get('missing') else None
    else:
        value = metrics.get('breadth', {}).get(metric)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def evaluate_check(check, facts):
    """Never infer success from prose, incomplete sessions, changed samples or later data."""
    result = {**deepcopy(check), 'state': 'insufficient', 'reason': 'metric_missing', 'observed_at': facts['as_of'], 'observations': []}
    day, target = facts['trade_date'], check.get('target_trade_date')
    if not target:
        return result
    if datetime.fromisoformat(check['registered_at']) > datetime.fromisoformat(facts['collected_at']):
        return {**result, 'reason': 'registration_after_observation'}
    if day < target or (day == target and facts['intraday']):
        return {**result, 'state': 'waiting', 'reason': 'window_not_complete'}
    if day > target:
        return {**result, 'state': 'expired', 'reason': 'missed_session'}
    if not check.get('rule'):
        return {**result, 'state': 'review_required', 'reason': 'qualitative_condition'}
    if (facts['coverage']['status'] != 'complete' or check.get('coverage_status') != 'complete'
            or not check.get('universe_hash') or check['universe_hash'] != facts.get('universe_hash')):
        return {**result, 'reason': 'coverage_or_universe_changed'}
    outcomes = {}
    for name in ('rule', 'invalidation_rule'):
        rule = check.get(name)
        if not rule:
            continue
        value = _value(facts, rule['metric'])
        threshold = rule['value']
        passed = None if value is None else {'gt': value > threshold, 'gte': value >= threshold,
                                             'lt': value < threshold, 'lte': value <= threshold}[rule['operator']]
        outcomes[name] = passed
        result['observations'].append({'kind': name, **rule, 'observed_value': value, 'passed': passed})
    # Invalidation has precedence even when the positive condition also passes.
    if outcomes.get('invalidation_rule') is True:
        state = 'invalidated'
    elif any(v is None for v in outcomes.values()):
        return result
    else:
        state = 'met' if outcomes['rule'] else 'not_met'
    return {**result, 'state': state, 'reason': 'evaluated'}


def continuity(previous, facts):
    previous = previous or {}
    old_report = previous.get('report', {})
    # A same-session refresh preserves the prior session's frozen verification set.
    if previous.get('trade_date', '') < facts['trade_date']:
        checks = old_report.get('registered_checks', []) if not previous.get('intraday', True) else []
    else:
        checks = old_report.get('continuity', {}).get('checks', [])
    return {'source_run_id': checks[0]['source_run_id'] if checks else None,
            'checks': [evaluate_check(c, facts) for c in checks]}


def enrich_report(payload, previous=None):
    """Host-owned metadata. The model cannot overwrite registrations or verdicts."""
    previous = previous or {}
    checks = []
    for i, check in enumerate(payload['analysis']['next_checks']):
        checks.append({**deepcopy(check), 'id': f"{payload['run_id']}:{i}", 'source_run_id': payload['run_id'],
                       'registered_at': payload['analyzed_at'], 'registered_trade_date': payload['trade_date'],
                       'target_trade_date': payload.get('next_trade_date'), 'horizon': 'next_session_close',
                       'universe_hash': payload.get('universe_hash'), 'coverage_status': payload['coverage']['status']})
    old = previous.get('analysis')
    revision = None if not old else {
        'previous_run_id': previous['run_id'], 'previous_trade_date': previous['trade_date'],
        'previous_as_of': previous['as_of'], 'previous_title': old['title'], 'previous_stage': old['stage'],
        'current_stage': payload['analysis']['stage'],
        'changed': (old['stage']['kind'], old['stage']['stages'], old['stage']['status']) !=
                   (payload['analysis']['stage']['kind'], payload['analysis']['stage']['stages'], payload['analysis']['stage']['status']),
        'explanation': payload['analysis']['stage']['rationale']}
    result = {'version': '1.0', 'continuity': continuity(previous, payload), 'registered_checks': checks,
            'revision': revision, 'purpose': 'market_observation', 'execution': 'not_assessed',
            'parameter_status': 'unvalidated', 'data_gaps': [
                {'id': 'limit_events', 'label': '涨停 / 炸板与精确连板梯队', 'impact': '无法确认封板率、一进二与梯队断层',
                 'required': '逐日限价、全量事件池、板数及冻结前日分母', 'status': 'missing'},
                {'id': 'themes', 'label': '题材持续性与登记板块验证', 'impact': '无法确认题材连续领涨或历史扩散',
                 'required': '带时点的题材成分、统一板块行情、冻结登记名单', 'status': 'missing'},
                {'id': 'execution', 'label': '回封事件与可成交性', 'impact': '无法把统计观察转为可执行买点',
                 'required': '开板 / 回封事件时间、报价与队列；分时价格不能替代排队成交', 'status': 'missing'},
                {'id': 'dragon_tiger', 'label': '龙虎榜明细', 'impact': '不能核对上榜席位或买卖差额',
                 'required': '交易日、发布时间、上榜原因与席位买卖明细', 'status': 'missing'}]}
    supplement = payload.get('supplement', {})
    if payload.get('report_context', {}).get('ready'):
        result['data_gaps'] = []
        return result
    if supplement.get('statistics', {}).get('status') == 'available' and all(
            supplement.get('pools', {}).get(k, {}).get('status') == 'available' for k in ('up', 'down', 'broken')):
        result['data_gaps'] = [g for g in result['data_gaps'] if g['id'] != 'limit_events']
    if supplement.get('dragon_tiger', {}).get('status') == 'available':
        for gap in result['data_gaps']:
            if gap['id'] == 'dragon_tiger':
                gap.update(impact='已取得上榜股票记录；原始发布时间和完整席位证据仍未核验',
                           required='原始发布时间、上榜原因与席位买卖明细', status='partial')
    return result


def _text(value):
    return escape(str(value if value is not None else '—'), quote=True)


def _num(value, percent=False):
    if value is None:
        return '—'
    return f'{value * (100 if percent else 1):,.2f}' + ('%' if percent else '')


def stage_label(position):
    return ' ↔ '.join(STAGES[s] for s in position['stages']) or '暂不定位'


def _curve(position):
    names = list(STAGES) + ['ice']
    points = [(48, 150), (168, 125), (288, 65), (408, 30), (528, 76), (648, 137), (768, 150)]
    active = set(position['stages'])
    if position['kind'] == 'between' and position['stages'] == ['retreat', 'ice']:
        indices = {5, 6}
    else:
        indices = {i for i, name in enumerate(names[:6]) if name in active}
    markers = ''.join(f'<circle cx="{x}" cy="{y}" r="{8 if i in indices else 4}" class="{"active" if i in indices else "dot"}"/><text x="{x}" y="185" text-anchor="middle">{_text(STAGES[names[i]])}</text>' for i, (x, y) in enumerate(points))
    if indices:
        x = sum(points[i][0] for i in indices) / len(indices)
        y = min(points[i][1] for i in indices) - 16
        markers += f'<text x="{x}" y="{y}" text-anchor="middle" style="fill:#a45b0b;font-weight:700">当前</text>'
    return f'<svg viewBox="0 0 816 205" role="img" aria-label="{_text(stage_label(position))}"><path d="M48 150 C110 150 130 140 168 125 S245 80 288 65 S370 15 408 30 S490 45 528 76 S610 135 648 137 S735 160 768 150"/>{markers}</svg>'


def render_html(payload):
    """A conclusion-first Chinese trading review; provenance stays in one disclosure."""
    for key in ('trade_date', 'as_of', 'collected_at', 'analyzed_at', 'run_id', 'analysis', 'metrics', 'coverage', 'evidence'):
        if key not in payload:
            raise ValueError(f'Missing report field: {key}')
    a = payload['analysis']
    d = a.get('decision') or {}
    stage = a['stage']
    def p(value, cls=''):
        return f'<p class="{cls}">{_text(value)}</p>'
    def row(label, value):
        return f'<div class="conclusion-row"><dt>{_text(label)}</dt><dd>{_text(value)}</dd></div>'
    def bullets(values):
        return '<ul>' + ''.join(f'<li>{_text(v)}</li>' for v in values) + '</ul>'
    def card(title, body, cls=''):
        return f'<article class="{cls}"><h3>{_text(title)}</h3>{body}</article>'
    body = f'<header><h1>情绪周期 · 综合看板</h1><p class="subtitle">短线情绪复盘 · 今日结论 / 明日预案 / 买点聚焦 · {_text(payload["trade_date"])}</p>'
    confidence = {'low': '较低', 'medium': '中等', 'high': '较高'}.get(d.get('confidence'), '')
    body += '<div class="headline-badges">'
    if confidence:
        body += f'<span class="confidence">置信度 {_text(confidence)}</span>'
    body += f'<strong class="stage-badge">{_text(stage_label(stage))}</strong></div></header>'
    body += '<section class="conclusion"><h2>① 结论区</h2><div class="today">'
    body += f'<h3 class="evaluation">今日评价 <span class="rhythm">节奏：{_text(d.get("rhythm", DIRECTIONS[a["direction"]]))}</span></h3>'
    body += p(d.get('assessment', a['summary']), 'assessment')
    rows = [('周期定位', d.get('cycle_note', stage['rationale'])), ('短线情绪', d.get('short_term', a['direction_reason'])),
            ('指数 · 趋势端', d.get('index_context')), ('盘面关键变化', d.get('structure')), ('板块与承接', d.get('theme_verdict')),
            ('今日应对', d.get('today_strategy')), ('买点判定', d.get('buy_point_verdict'))]
    body += '<dl>' + ''.join(row(k, v) for k, v in rows if v) + '</dl>'
    body += '</div><div class="cycle"><span class="cycle-title">当前周期位置</span>' + _curve(stage) + '</div></section>'
    if d:
        body += '<section class="tomorrow"><h2>② 明日预判</h2>'
        body += f'<h3 class="forecast">{_text(payload.get("next_trade_date", "下一交易日"))} · {_text(d["tomorrow_title"])}</h3>'
        body += p(d['tomorrow_expectation'], 'expectation') + '<h3>明日机会</h3>'
        for path in d['paths']:
            label = '左侧' if path['side'] == 'left' else '右侧'
            body += f'<div class="opportunity"><b>{label}</b><div><p><strong>触发</strong> {_text(path["trigger"])}</p><p><strong>失效</strong> {_text(path["invalidation"])}</p></div></div>'
        body += '<h3 class="subheading">明日边界</h3>'
        for boundary in d['boundaries']:
            body += card(boundary['topic'], bullets([boundary['strengthens'], boundary['invalidates']]), 'boundary')
        body += '<h3 class="subheading">明日操作</h3>' + bullets(d['actions']) + '</section>'
        body += '<section class="focus"><h2>③ 明日买点聚焦</h2>'
        for path in d['paths']:
            side = '左侧路径' if path['side'] == 'left' else '右侧路径'
            content = p(path['action'], 'path-action')
            if path['sectors']:
                content += '<div class="sector-tags">' + ''.join(f'<span>{_text(s)}</span>' for s in path['sectors']) + '</div>'
            for stock in path['candidates']:
                content += '<div class="stock"><div class="stock-heading"><strong>' + _text(stock['name']) + '</strong><span>' + _text(stock['symbol']) + '</span><b>' + _text(stock['role']) + '</b></div>'
                content += p(stock['reason']) + '<p><b>关注条件</b> ' + _text(stock['trigger']) + '</p><p><b>取消条件</b> ' + _text(stock['invalidation']) + '</p></div>'
            body += card(side + ' · ' + path['title'], content, 'path ' + path['side'])
        body += '</section>'
    else:
        body += '<section class="tomorrow"><h2>② 下一交易日观察</h2>'
        for check in a.get('next_checks', []):
            body += card(check['observe'], bullets([check['strengthens'], check['invalidates']]))
        body += '</section>'
    breadth = payload['metrics']['breadth']
    stats = payload.get('supplement', {}).get('statistics', {}).get('data') or {}
    metric_items = [('上涨', breadth.get('rising')), ('下跌', breadth.get('falling')), ('上涨占比', _num(breadth.get('positive_ratio'), True)),
                    ('涨幅中位数', _num(breadth.get('median')) + '%'), ('涨停', stats.get('limit_up_stock_count')),
                    ('炸板', stats.get('open_stock_count')), ('封板率', _num(stats.get('seal_rate'), True))]
    body += '<section class="data-section"><h2>④ 情绪数据</h2><div class="metrics">' + ''.join(f'<div class="metric"><span>{_text(k)}</span><strong>{_text(v)}</strong></div>' for k, v in metric_items if v is not None) + '</div>'
    ladders = payload.get('supplement', {}).get('ladders', [])
    for ladder in ladders:
        if ladder.get('sample'):
            levels = '　'.join(f'{r["level"]} 板 {r["count"]} 家' for r in ladder['levels'])
            body += p({'main': '主板', 'growth': '创业板', 'star': '科创板', 'beijing': '北交所'}[ladder['board']] + '：' + levels)
    body += '</section>'
    # Source attribution remains per fact, but never competes with the actual verdict.
    body += '<details class="sources"><summary>查看数据来源与判断依据</summary><div class="source-body">'
    for key, label in [('supports', '主要依据'), ('counters', '相反证据')]:
        body += '<h3>' + label + '</h3>' + bullets([c['text'] for c in a.get(key, [])])
    body += '<h3>来源明细</h3><table><thead><tr><th>数据项</th><th>来源</th><th>获取时间</th></tr></thead><tbody>'
    for e in payload['evidence']:
        body += f'<tr><td>{_text(e["title"])}</td><td>{_text(e["source"])}</td><td>{_text(e["observed_at"])}</td></tr>'
    body += '</tbody></table>'
    if a.get('limitations'):
        body += '<h3>口径说明</h3>' + bullets(a['limitations'])
    for e in payload['evidence']:
        body += f'<details id="ev-{_text(e["id"])}"><summary>{_text(e["title"])}</summary><pre>{_text(json.dumps(e["content"], ensure_ascii=False, indent=2, allow_nan=False))}</pre></details>'
    body += '</div></details>'
    generated_at = datetime.fromisoformat(payload['analyzed_at']).astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
    body += f'<footer>行情日期 {_text(payload["trade_date"])} · {"盘中" if payload.get("intraday") else "收盘复盘"} · 生成 {_text(generated_at)}（北京时间）</footer>'
    css = '''*{box-sizing:border-box}body{margin:0;background:#f4f6f8;color:#29282c;font:16px/1.8 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}main{max-width:1040px;margin:0 auto;padding:32px 22px}header,section{background:#fff;border:1px solid #ebedf0;border-radius:18px;padding:28px 34px;margin-bottom:22px;box-shadow:0 2px 6px #20242b06}h1{font-size:30px;line-height:1.4;margin:0 0 10px}h2{font-size:23px;line-height:1.4;margin:0 0 20px;padding-left:13px;border-left:5px solid #782fc0}h3{font-size:18px;line-height:1.6;margin:0 0 10px}p{margin:6px 0;overflow-wrap:anywhere}.subtitle{color:#89868b;font-size:14px}.headline-badges{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin-top:20px}.confidence{border:1px solid #b68139;color:#a66b26;padding:3px 14px;border-radius:30px;font-size:13px}.stage-badge{border-radius:12px;background:#cf7009;color:white;padding:12px 24px;font-size:22px}.today{background:#f8f0fd;border:1px solid #d8bae8;border-radius:13px;padding:22px}.evaluation{color:#5a2793}.rhythm{font-size:14px;color:#fff;background:#7b2cc1;border-radius:30px;padding:4px 14px;margin-left:6px;white-space:nowrap}.assessment{color:#a85c09;font-weight:650;font-size:17px;margin-bottom:14px}dl{margin:0}.conclusion-row{display:grid;grid-template-columns:120px minmax(0,1fr);gap:14px;margin:12px 0}dt{color:#89838d}dd{margin:0;white-space:pre-line;overflow-wrap:anywhere}.cycle{padding:18px 10px 0}.cycle-title{font-size:13px;color:#8c8397}svg{width:100%;display:block;max-height:180px}svg path{fill:none;stroke:#887bb6;stroke-width:3}svg .dot{fill:#b6becd}svg .active{fill:#ce6c09;stroke:#fff;stroke-width:3}svg text{font-size:12px;fill:#777080}.tomorrow{background:#fffbea;border-color:#eddfac}.tomorrow h2,.focus h2{border-left-color:#cc790b}.forecast{color:#a7710a;font-size:21px}.expectation{color:#86651d;margin-bottom:22px}.opportunity{display:flex;gap:18px;margin:14px 0;color:#9b691b}.opportunity>b{color:#b82632;white-space:nowrap}.opportunity p{margin:0 0 4px}.subheading{margin-top:24px}article{background:#ffffff94;border:1px solid #e6e3db;border-radius:12px;padding:18px 20px;margin:12px 0}.boundary{border-left:4px solid #d8d7d3}.boundary ul{margin:0}ul{margin:10px 0;padding-left:22px}li{padding-left:2px;margin:7px 0;overflow-wrap:anywhere}.path{border-left:4px solid #cb790a;background:#fffdf2;padding:22px}.path.left{border-left-color:#bf2537}.path h3{color:#a66d14}.path.left h3{color:#ac2939}.path-action{font-weight:600;color:#9d6b18}.sector-tags{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}.sector-tags span{border:1px solid #dcd6c6;background:#fff;border-radius:20px;padding:1px 12px;color:#997120;font-size:14px}.stock{border:1px solid #e9e5da;border-radius:10px;padding:15px 18px;margin-top:12px}.stock-heading{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.stock-heading>strong{font-size:19px;color:#a36c0d}.stock-heading>span{font-size:12px;color:#948c7b}.stock-heading>b{font-size:13px;line-height:1.5;font-weight:500;background:#f0f5ff;color:#4168a8;border:1px solid #c1d1ed;border-radius:20px;padding:3px 10px}.stock p{font-size:14px}.stock p>b{color:#867448}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.metric{border:1px solid #eee9e2;border-radius:10px;padding:14px;background:#fcfbf9}.metric span{display:block;font-size:13px;color:#8b8581}.metric strong{font-size:25px;font-variant-numeric:tabular-nums}.data-section p{font-size:14px;color:#77716b}.sources{background:white;border:1px solid #e5e6e8;border-radius:12px;padding:15px 22px;color:#79747e;font-size:13px}.source-body{padding-top:20px}.source-body h3{font-size:15px}.source-body details{border-top:1px solid #eee;padding:8px 0}summary{cursor:pointer}pre{font-size:11px;white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f6f7;padding:12px;border-radius:8px}table{border-collapse:collapse;width:100%;table-layout:fixed;font-size:11px;margin:12px 0}th,td{text-align:left;vertical-align:top;border-bottom:1px solid #eee;padding:8px;overflow-wrap:anywhere}footer{font-size:12px;color:#99919c;padding:18px 4px;text-align:center}@media(max-width:600px){body{font-size:14px}main{padding:14px 10px}header,section{padding:20px 16px;margin-bottom:14px;border-radius:13px}h1{font-size:24px}h2{font-size:20px}h3{font-size:16px}.subtitle{font-size:12px}.stage-badge{font-size:18px}.today{padding:16px 13px}.assessment{font-size:15px}.conclusion-row{grid-template-columns:82px minmax(0,1fr);gap:10px;margin:13px 0}.evaluation{line-height:2.2}.rhythm{font-size:12px;padding:3px 10px}.forecast{font-size:18px}.opportunity{gap:12px}article,.path{padding:15px 13px}.stock{padding:12px}.stock-heading>strong{font-size:17px}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.metric strong{font-size:23px}.sources{padding:14px}.cycle{padding:16px 0 0}svg text{font-size:13px}}@media print{body{background:white}main{max-width:none;padding:0}header,section{box-shadow:none}article,.stock{break-inside:avoid}.sources{display:none}}'''
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>情绪周期综合看板 · ' + _text(a['title']) + '</title><style>' + css + '</style></head><body><main>' + body + '</main></body></html>'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path, help='Validated overview envelope JSON')
    parser.add_argument('--output', required=True, type=Path, help='Standalone HTML output')
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding='utf-8'), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    rendered = render_html(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding='utf-8')


if __name__ == '__main__':
    main()
