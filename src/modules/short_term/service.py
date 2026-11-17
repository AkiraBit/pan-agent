"""Durable, single-process execution and an opt-in premarket schedule."""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

from marketdata.short_term import TZ
from pan_agent import EventType

from src.platform.ai.ai_failover import get_configured_failover_client
from src.platform.ai.responses_tool_client import enable_reasoning_tools
from src.platform.persistence.database import SessionLocal
from src.platform.persistence.models import EmotionWorkspace
from src.platform.scheduling.trading_calendar import is_trading_day
from .agent import run_analysis
from .enrichment import enrich_facts
from .lifecycle_repository import LifecycleRepository
from .monitoring import monitor_once
from .review_agent import run_review
from .regulatory_repository import RegulatoryRepository
from .session_validation import validation_tick, SessionValidationRepository
from .facts import collect_facts, utc_now
from .repository import EmotionRepository, WorkspaceError, contextual_evidence
from .schemas import RunCreate, WorkspaceSettings

logger = logging.getLogger(__name__)

# Market collection has up to 70 + 70 + 35 + 35 seconds of sequential
# source budgets. Original PDFs and OCR also need a cold-start allowance.
COLLECTION_TIMEOUT_SECONDS = 225
VERIFICATION_TIMEOUT_SECONDS = 240


class EmotionRunner:
    def __init__(self, session_factory=SessionLocal, *, collector=collect_facts, analyzer=run_analysis, client_factory=get_configured_failover_client, enricher=enrich_facts, reviewer=run_review):
        self.session_factory = session_factory
        self.collector, self.analyzer, self.client_factory = collector, analyzer, client_factory
        self.enricher, self.reviewer = enricher, reviewer
        self.tasks = {}
        self.scheduler = None

    def read(self, operation):
        with self.session_factory() as db:
            return operation(EmotionRepository(db))

    async def write(self, operation):
        pending = asyncio.create_task(asyncio.to_thread(self.read, operation))
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            await pending
            raise

    def start(self, identity):
        if identity in self.tasks:
            return
        task = asyncio.create_task(self.execute(identity))
        self.tasks[identity] = task
        task.add_done_callback(lambda _: self.tasks.pop(identity, None))

    async def execute(self, identity):
        client = None
        try:
            if not await self.write(lambda r: r.claim_run(identity)):
                return
            def inputs(repository):
                row = repository.get_run(identity)
                return SimpleNamespace(id=row.id, target_trade_date=row.target_trade_date, inputs=row.inputs)
            run = await asyncio.to_thread(self.read, inputs)
            def make_client():
                with self.session_factory() as db:
                    return enable_reasoning_tools(self.client_factory(db))
            client = await asyncio.to_thread(make_client)
            review = run.inputs.get('kind') == 'postmarket'
            overview = run.inputs.get('kind') == 'overview'
            if overview:
                from .overview_facts import collect_overview
                from .overview_repository import SKILL_ID
                from src.modules.administration import builtin_skills, longbridge_mcp

                async def skill_check():
                    item = await asyncio.to_thread(self.read, lambda r: builtin_skills.status(r.db, SKILL_ID))
                    if not item['available']:
                        raise ValueError('overview_skill_unavailable')

                async def query(tool, arguments):
                    await skill_check()
                    with self.session_factory() as db:
                        return await longbridge_mcp.remote(db, tool, arguments)

                await skill_check()
                await self.write(lambda r: r.append_event(identity, 'collecting', {'source': 'longbridge_mcp'}))
                facts = await asyncio.wait_for(collect_overview(query, run.inputs.get('previous')), 300)
                from .overview_supplement import supplement
                async def supplementary_query(operation, arguments):
                    # The configured adapter supplies the report's specialist data.
                    from src.platform.marketdata.fuyao_business import fetch as fetch_fuyao
                    with self.session_factory() as source_db:
                        bind = source_db.get_bind()
                    return await fetch_fuyao(operation, arguments, bind=bind)
                facts = await supplement(facts, supplementary_query)
                from .overview_context import collect_report_context
                context = await collect_report_context(facts, supplementary_query)
                if not context['ready']:
                    await self.write(lambda r: r.append_event(identity, 'data_required', {'missing': context['missing']}))
                    raise ValueError('overview_report_data_missing')
                from .facts import evidence
                facts['evidence'] += [evidence('note:' + n['id'], 'user_context', n['content'][:100], 'user',
                    {'text': n['content'], 'verification': 'user_unverified'}, facts['collected_at'], status='user_unverified') for n in run.inputs['notes']]
                await self.write(lambda r: r.save_facts(identity, facts))
                await self.write(lambda r: r.append_event(identity, 'analyzing', {'source': 'longbridge_mcp', 'quote_count': facts['coverage']['valid']}))
            elif review:
                facts = {'evidence': run.inputs['evidence']}
                await self.write(lambda r: r.append_event(identity, 'analyzing', {'mode': 'postmarket'}))
            else:
                await self.write(lambda r: r.append_event(identity, 'collecting', {'source': 'live_providers'}))
                memory_symbols = list(dict.fromkeys(s for p in run.inputs['memory'] for s in p['symbols']))[:12]
                try:
                    facts = await asyncio.wait_for(self.collector(run.inputs['settings'].get('focus_symbols', []), memory_symbols), COLLECTION_TIMEOUT_SECONDS)
                except TimeoutError as exc:
                    raise ValueError('market_collection_timeout') from exc
                facts['capabilities']['continuous_monitoring'] = True
                facts['monitoring_configuration'] = {
                    'auto_start_after_publication': bool(run.inputs['settings'].get('monitoring_enabled')),
                    'continuous_interval_seconds': run.inputs['settings'].get('monitor_interval_seconds', 30),
                    'auction_interval_seconds': 5, 'coverage': 'discrete_source_timed_samples_not_full_ticks',
                }
                if self.enricher:
                    await self.write(lambda r: r.append_event(identity, 'collecting', {'source': 'primary_documents_and_adjusted_prices'}))
                    try:
                        facts = await asyncio.wait_for(self.enricher(facts, run.inputs), VERIFICATION_TIMEOUT_SECONDS)
                    except TimeoutError as exc:
                        raise ValueError('source_verification_timeout') from exc
                await self.write(lambda r: RegulatoryRepository(r.db).retain(facts.get('regulatory_events', [])))
                facts['evidence'] += contextual_evidence(run.inputs, facts['collected_at'])
                await self.write(lambda r: r.save_facts(identity, facts))
                await self.write(lambda r: r.append_event(identity, 'analyzing', {
                    'reference_trade_date': facts['reference_trade_date'], 'quote_count': len(facts['quotes']),
                    'evidence_count': len(facts['evidence']), 'memory_revisions': [p['revision'] for p in run.inputs['memory']]}))
            runner = self

            class Sink:
                async def publish(self, event):
                    if event.type == EventType.ANSWER_TOKEN:
                        return  # Draft prose is never the published financial conclusion.
                    allowed = {'step', 'status', 'tool_name', 'duration_ms', 'input_tokens', 'output_tokens',
                               'total_tokens', 'model', 'error_code', 'usage_available', 'source',
                               'call_id', 'ok', 'attempt_count'}
                    data = {k: v for k, v in event.data.items() if k in allowed}
                    if event.data.get('tool'):
                        data['tool_name'] = event.data['tool']
                    if event.data.get('tool') in {'validate_analysis', 'validate_review', 'validate_overview'} and event.type == EventType.TOOL_COMPLETED:
                        result = event.data.get('data') or {}
                        data['accepted'] = result.get('accepted')
                        if result.get('errors'):
                            data['validation_error'] = str(result['errors'])[:2500]
                    await runner.write(lambda r: r.append_event(identity, event.type.value, data))
                    status = await asyncio.to_thread(runner.read, lambda r: r.get_run(identity).status)
                    if status != 'running':
                        raise asyncio.CancelledError()

            if overview:
                from .overview_agent import run_overview
                from .overview_repository import OverviewRepository
                analysis = await run_overview(client, run, facts, Sink(), skill_check)
                await self.write(lambda r: OverviewRepository(r.db).publish(identity, facts, analysis, client.used_model_label))
            elif review:
                publication = await self.reviewer(client, run, facts, Sink())
                await self.write(lambda r: LifecycleRepository(r.db).publish_review(identity, publication, client.used_model_label))
            else:
                publication = await self.analyzer(client, run, facts, Sink())
                published = await self.write(lambda r: r.publish(identity, publication, client.used_model_label))
                if run.inputs['settings'].get('monitoring_enabled'):
                    await self.write(lambda r: LifecycleRepository(r.db).set_monitor(published['id'], True))
        except asyncio.CancelledError:
            await self.write(lambda r: r.finish_failed(identity, 'run_cancelled', 'cancelled'))
        except Exception as exc:
            code = str(exc) if isinstance(exc, ValueError) and len(str(exc)) < 80 else 'analysis_failed'
            logger.warning('Emotion analysis failed: run=%s code=%s', identity, code)
            await self.write(lambda r: r.finish_failed(identity, code))
        finally:
            # The transport owns AsyncOpenAI/httpx clients, not the publication.
            for transport, _ in getattr(client, 'candidates', []):
                try:
                    await transport.client.close()
                except Exception:
                    pass

    async def cancel(self, identity):
        await self.write(lambda r: r.finish_failed(identity, 'run_cancelled', 'cancelled'))
        if task := self.tasks.get(identity):
            task.cancel()

    async def recover_pending(self):
        await self.write(lambda r: r.recover())
        await self.write(lambda r: LifecycleRepository(r.db).recover())
        if self.scheduler is None:
            self.scheduler = asyncio.create_task(self.schedule_loop())

    async def schedule_once(self, now=None):
        now = (now or utc_now()).astimezone(TZ)
        if not is_trading_day('CN', now) or now.strftime('%H:%M') > '09:10':
            return
        def maybe_create(repository):
            if SessionValidationRepository(repository.db).owns_date(now.date().isoformat()):
                return None  # An armed validation owns its premarket and next-memory runs.
            workspace = repository.db.get(EmotionWorkspace, 1)
            if not workspace:
                return None
            settings = WorkspaceSettings.model_validate(workspace.settings)
            if not settings.schedule_enabled or now.strftime('%H:%M') < settings.schedule_time:
                return None
            row, created = repository.create_run(RunCreate(
                request_key='schedule:' + now.date().isoformat(), target_trade_date=now.date(), language=settings.language), now=now)
            return row.id if created else None
        try:
            identity = await self.write(maybe_create)
            if identity:
                self.start(identity)
        except WorkspaceError:
            pass  # A manual run has the lease. Try again next tick, with the same idempotency key.

    async def schedule_loop(self):
        while True:
            # A failed collector must not suppress orchestration/heartbeat. Run
            # validation first so its fixed deadlines own the controlled day.
            for operation in (lambda: validation_tick(self), self.schedule_once, lambda: monitor_once(self)):
                try:
                    await operation()
                except asyncio.CancelledError:
                    return
                except Exception:
                    logger.warning('Emotion schedule check failed', exc_info=True)
            await asyncio.sleep(5)

    async def shutdown(self):
        if self.scheduler:
            self.scheduler.cancel()
            await asyncio.gather(self.scheduler, return_exceptions=True)
            self.scheduler = None
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


emotion_runner = EmotionRunner()
