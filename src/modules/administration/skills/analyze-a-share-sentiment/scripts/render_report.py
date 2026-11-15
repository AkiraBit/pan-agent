#!/usr/bin/env python3
"""Portable, offline sentiment report renderer. Python standard library only."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
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
    return f'<svg viewBox="0 0 816 205" role="img" aria-label="{_text(stage_label(position))}"><path d="M48 150 C110 150 130 140 168 125 S245 80 288 65 S370 15 408 30 S490 45 528 76 S610 135 648 137 S735 160 768 150"/>{markers}</svg>'


def render_html(payload):
    """Render a validated overview envelope, not an arbitrary model-supplied HTML string."""
    for key in ('trade_date', 'as_of', 'collected_at', 'analyzed_at', 'run_id', 'analysis', 'metrics', 'coverage', 'evidence'):
        if key not in payload:
            raise ValueError(f'Missing report field: {key}')
    analysis = payload['analysis']
    report = payload.get('report') or enrich_report(payload)
    stage = analysis['stage']
    known = {e['id']: e for e in payload['evidence']}
    def refs(ids):
        return '<div class="refs">' + ' · '.join(f'<a href="#ev-{_text(i)}">{_text(known[i]["title"])}</a>' for i in ids if i in known) + '</div>'
    def section(title, body, cls=''):
        return f'<section class="{cls}"><h2>{_text(title)}</h2>{body}</section>'
    def paragraph(value):
        return f'<p>{_text(value)}</p>'
    breadth = payload['metrics']['breadth']
    cards = ''.join(f'<div class="metric"><span>{title}</span><strong>{_text(value)}</strong></div>' for title, value in [
        ('上涨家数', breadth.get('rising')), ('下跌家数', breadth.get('falling')),
        ('上涨占比', _num(breadth.get('positive_ratio'), True)), ('涨幅中位数（%）', _num(breadth.get('median')))])
    summary = f'<div class="eyebrow">A-SHARE SENTIMENT · {_text(payload["trade_date"])}</div><h1>{_text(analysis["title"])}</h1><p class="lead">{_text(analysis["summary"])}</p><div class="pills"><b>{_text(DIRECTIONS[analysis["direction"]])}</b><b>{_text(stage_label(stage))}</b><b>{_text(STATUSES[stage["status"]])}</b></div>'
    body = '<header>' + summary + '</header>'
    body += section('01 · 周期定位', _curve(stage) + paragraph(stage['rationale']) + refs(stage['evidence_ids']) +
                    '<small>曲线表示阶段关系；双点表示相邻区间，不是进度、概率或未来走势。</small>')
    body += section('02 · 今日评价与市场数据', '<div class="metrics">' + cards + '</div>' + paragraph(analysis['direction_reason']) +
                    f'<small>行情时点 {_text(payload["as_of"])} · {"盘中暂定" if payload.get("intraday") else "收盘快照"} · 有效样本 {_text(payload["coverage"]["valid"])} / 目录 {_text(payload["coverage"]["directory_total"])}</small>')
    axes = ''.join(f'<article><h3>{label} · {_text(DIRECTIONS[analysis[key]["state"]])}</h3>{paragraph(analysis[key]["explanation"])}{refs(analysis[key]["evidence_ids"])}</article>' for key, label in [('loss_relief', '亏损缓和'), ('profit_diffusion', '盈利扩散')])
    groups = ''.join(f'<article><h3>{g["group"]} · {_text(STATUSES[g["status"]])}</h3>{paragraph(g["explanation"])}{refs(g["evidence_ids"])}</article>' for g in analysis['groups'])
    body += section('03 · 情绪与结构', '<div class="grid">' + axes + groups + '</div>')
    validation = ''
    for check in report['continuity']['checks']:
        observations = ''.join(paragraph(f'{METRICS[o["metric"]]}：实际 {_num(o["observed_value"])}；登记 {o["operator"]} {o["value"]}（待回测）') for o in check['observations'])
        validation += f'<article><h3>{_text(check["observe"])}</h3><b>{_text(STATUSES[check["state"]])}</b>{paragraph(REASONS[check["reason"]])}{paragraph("原加强条件：" + check["strengthens"])}{paragraph("原反证条件：" + check["invalidates"])}<small>登记 {_text(check["registered_at"])} → 验证 {_text(check["target_trade_date"])} 收盘</small>{observations}</article>'
    body += section('04 · 上次预期 → 本次验证', validation or '<p>尚无可用的前一交易日登记条件。首次生成不补造历史命中记录。</p>')
    revision = report.get('revision')
    if revision:
        body += section('判断修订记录', paragraph(f'原判断（{revision["previous_as_of"]}）：{revision["previous_title"]}') +
                        paragraph(f'{stage_label(revision["previous_stage"])} → {stage_label(revision["current_stage"])}') +
                        paragraph(revision['explanation']) + '<small>原判断按发布时点保留；本次解释不覆盖原记录。</small>')
    conditions = ''.join(f'<article><h3>{_text(c["observe"])}</h3><small>{_text(c["window"])}</small><p><b>加强判断</b> {_text(c["strengthens"])}</p><p><b>推翻判断</b> {_text(c["invalidates"])}</p><small>{"已登记数值条件 · 参数待回测 · 次日收盘验证" if c.get("rule") else "文字观察条件 · 需要复核，不能自动认定命中"}</small></article>' for c in analysis['next_checks'])
    body += section('05 · 下一交易日观察预案', conditions + '<p class="note">观察条件成立不等于可以成交。本页未评估账户与仓位。普通 A 股当日新买入部分不能在同日卖出；撤销未成交委托与卖出已成交股份必须分开。</p>')
    claims = ''.join(f'<article><h3>{label}</h3>' + ''.join(paragraph(c['text']) + refs(c['evidence_ids']) for c in analysis[key]) + '</article>' for key, label in [('supports', '支持当前判断'), ('counters', '反证与其他解释')])
    body += section('06 · 依据与反证', '<div class="grid">' + claims + '</div>')
    supplement = payload.get('supplement')
    if supplement:
        stats = supplement['statistics']['data'] if supplement['statistics']['status'] == 'available' else None
        event_body = paragraph(f'扶摇 REST · 交易日 {supplement["trade_date"]} · 采集 {supplement["collected_at"]}')
        if stats:
            event_body += paragraph(f'供应商封板 {stats["limit_up_stock_count"]} 家；打开 {stats["open_stock_count"]} 家；封板率 {_num(stats["seal_rate"], True)}')
        else:
            event_body += paragraph('汇总指标暂不可用或未通过口径核验。')
        for ladder in supplement['ladders']:
            levels = ' · '.join(f'{x["level"]} 板 {x["count"]} 家' for x in ladder['levels']) or '没有可展示记录'
            event_body += f'<article><h3>{_text({"main":"主板","growth":"创业板","star":"科创板","beijing":"北交所"}[ladder["board"]])}</h3>{paragraph(levels)}<small>样本 {ladder["sample"]} · 排除或未知 {ladder["excluded_or_unknown"]} · {"池完整" if ladder["status"] == "available" else "池或字段不完整，不能据此认定梯队空缺"}</small></article>'
        event_body += '<small>汇总与过滤后梯队各用各自分母；页面档位晋级率不等于冻结队列晋级。龙虎榜原始记录见证据，单日和多日不得叠加。</small>'
        body += section('专项数据 · 涨跌停与接力梯队', event_body)
    gaps = ''.join(f'<article><h3>{_text(g["label"])} · {"部分可用" if g["status"] == "partial" else "缺失"}</h3>{paragraph(g["impact"])}<small>需要：{_text(g["required"])}</small></article>' for g in report['data_gaps'])
    body += section('07 · 数据缺口与待回测参数', gaps + '<p class="note">强势代理阈值：主板 5%、创业板 / 科创板 10%、北交所 15%，以及本页新增数值条件均未经预测能力校准。制度约束有规则依据，阶段解释有方法依据，均不等于收益已验证。</p>' + ''.join(paragraph(x) for x in analysis['limitations']))
    evidence = ''.join(f'<details id="ev-{_text(e["id"])}"><summary>{_text(e["title"])}</summary><p>{_text(e["source"])} · {_text(e["observed_at"])}</p><pre>{_text(json.dumps(e["content"], ensure_ascii=False, indent=2, allow_nan=False))}</pre><small>SHA256 {_text(e.get("content_hash"))}</small></details>' for e in payload['evidence'])
    body += section('来源与计算口径', evidence)
    body += f'<footer>采集 {_text(payload["collected_at"])} · 分析 {_text(payload["analyzed_at"])}<br>运行 {_text(payload["run_id"])} · Skill {_text(payload.get("skill", {}).get("version"))} · {_text(payload.get("model_label"))}<br>离线报告快照；不会自动刷新。源 JSON 与本页一起保存，以便复核。</footer>'
    css = '''*{box-sizing:border-box}body{margin:0;background:#f4f5f8;color:#232736;font:15px/1.75 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif}main{max-width:1120px;margin:auto;padding:32px 20px}header{background:#202838;color:#fff;padding:38px;border-radius:22px;margin-bottom:22px}.eyebrow{font-size:11px;letter-spacing:2px;color:#bdc8db}h1{font-size:30px;line-height:1.4;margin:12px 0}.lead{color:#dce3ef;max-width:900px}.pills{display:flex;flex-wrap:wrap;gap:8px}.pills b{font-size:12px;background:#ffffff16;border:1px solid #ffffff35;border-radius:30px;padding:5px 14px}section{background:white;border:1px solid #e3e6ec;border-radius:18px;padding:28px;margin:18px 0}h2{font-size:18px;margin:0 0 18px;color:#4e4584}h3{font-size:15px;margin:0 0 8px}p{margin:8px 0;overflow-wrap:anywhere}small,footer{font-size:12px;color:#687386}article{border:1px solid #e5e8ed;border-radius:12px;padding:18px;margin:8px 0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0}.metric{background:#f5f6fa;border-radius:12px;padding:16px}.metric span{display:block;color:#687386;font-size:12px}.metric strong{display:block;font-size:28px;font-variant-numeric:tabular-nums}.note{background:#faf5e8;border-left:3px solid #c59540;padding:14px 18px;font-size:13px}.refs{font-size:11px;margin-top:10px}a{color:#60539f;overflow-wrap:anywhere}svg{width:100%;display:block}svg path{fill:none;stroke:#887bb6;stroke-width:3}svg .dot{fill:#b6becd}svg .active{fill:#d17a30;stroke:#fff;stroke-width:3}svg text{font-size:12px;fill:#687386}details{border-top:1px solid #e5e8ed;padding:12px 0}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f6fa;padding:16px;border-radius:10px;font-size:11px}footer{padding:16px 4px}@media(max-width:640px){main{padding:14px 10px}header,section{padding:20px 16px;border-radius:14px}h1{font-size:23px}.grid{grid-template-columns:1fr}.metrics{grid-template-columns:1fr 1fr}.metric strong{font-size:24px}svg text{font-size:13px}}@media(prefers-color-scheme:dark){body{background:#131720;color:#e2e6ee}section{background:#1c2230;border-color:#343c4d}h2{color:#c1b5f0}article,details{border-color:#343c4d}.metric,pre{background:#262d3d}small,footer,.metric span{color:#a6b1c5}.note{background:#332f25}a{color:#c1b5f0}svg text{fill:#a6b1c5}}@media print{body{background:white}main{max-width:none;padding:0}header{background:white;color:#232736;border:1px solid #ccc}.lead{color:inherit}section,article{break-inside:avoid}details{display:block}footer{color:#555}}'''
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>' + _text(analysis['title']) + '</title><style>' + css + '</style></head><body><main>' + body + '</main></body></html>'


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
