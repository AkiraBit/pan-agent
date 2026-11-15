"""HTTP contracts only; authentication is installed by the application root."""
from datetime import date
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from fastapi.responses import HTMLResponse, JSONResponse

from src.platform.persistence.database import get_db
from src.web.errors import api_error
from .repository import EmotionRepository, WorkspaceError, run_dto
from .schemas import ContextCreate, ContextUpdate, RunCreate, WorkspaceSettings
from .service import emotion_runner
from .lifecycle_repository import LifecycleRepository
from .schemas import AuctionSettings, MonitorCommand, ReviewCreate

router = APIRouter()


@router.get('/sentiment-overview')
def sentiment_overview(db: Session = Depends(get_db)):
    from .overview_repository import OverviewRepository
    return OverviewRepository(db).view()


@router.get('/sentiment-overview/report')
def sentiment_report(format: str = 'html', run_id: str | None = None, db: Session = Depends(get_db)):
    from .overview_repository import OverviewRepository
    from .overview_reporting import engine
    from src.platform.persistence.models import EmotionRun
    payload = OverviewRepository(db).view()['overview']
    if run_id and (not payload or payload['run_id'] != run_id):
        run = db.get(EmotionRun, run_id)
        payload = run.inputs.get('published_overview') if run and run.status == 'succeeded' else None
    if not payload:
        raise api_error(404, 'emotion_overview_not_found', 'No published overview.')
    if format not in {'html', 'json'}:
        raise api_error(400, 'emotion_report_format', 'Use html or json.')
    filename = f'sentiment-{payload["trade_date"]}-{payload["run_id"][:8]}.{format}'
    headers = {'Content-Disposition': f'attachment; filename="{filename}"', 'Cache-Control': 'no-store',
               'X-Content-Type-Options': 'nosniff'}
    if format == 'json':
        # Download the original envelope; the normal application/json API wrapper
        # would add a transport-level data envelope unsuitable for the skill CLI.
        return JSONResponse(payload, headers=headers, media_type='application/vnd.panwatch.sentiment+json')
    return HTMLResponse(engine().render_html(payload), headers=headers)


from .overview_schema import OverviewRefresh


@router.post('/sentiment-overview/refresh', status_code=202)
async def refresh_overview(body: OverviewRefresh):
    from .overview_repository import OverviewRepository
    def create(repository):
        row, created = OverviewRepository(repository.db).create(body)
        return run_dto(row) if row else None, created
    try:
        row, created = await emotion_runner.write(create)
    except WorkspaceError as exc:
        raise api_error(409, 'emotion_' + str(exc), str(exc)) from None
    if created:
        emotion_runner.start(row['id'])
    return {'run': row, 'started': created}


def call(operation):
    try:
        return operation()
    except WorkspaceError as exc:
        code = str(exc)
        status = 404 if code.endswith('_not_found') else 409 if code in {'analysis_running', 'inputs_changed'} else 400
        raise api_error(status, 'emotion_' + code, code) from None


@router.get('/workspace')
def workspace(db: Session = Depends(get_db)):
    return EmotionRepository(db).workspace()


@router.put('/workspace/settings')
def settings(body: WorkspaceSettings, db: Session = Depends(get_db)):
    return call(lambda: EmotionRepository(db).save_settings(body))


@router.post('/runs', status_code=202)
async def create_run(body: RunCreate):
    def create(repository):
        row, created = repository.create_run(body)
        return run_dto(row), created
    try:
        row, created = await emotion_runner.write(create)
    except (WorkspaceError, ValueError) as exc:
        raise api_error(409 if str(exc) == 'analysis_running' else 400, 'emotion_' + str(exc), str(exc)) from None
    if created:
        emotion_runner.start(row['id'])
    return row


@router.get('/runs/{identity}')
def get_run(identity: str, db: Session = Depends(get_db)):
    return call(lambda: run_dto(EmotionRepository(db).get_run(identity)))


@router.post('/runs/{identity}/cancel')
async def cancel_run(identity: str, db: Session = Depends(get_db)):
    call(lambda: EmotionRepository(db).get_run(identity))
    await emotion_runner.cancel(identity)
    return {'ok': True}


@router.get('/publications/{identity}')
def publication(identity: str, db: Session = Depends(get_db)):
    return call(lambda: EmotionRepository(db).publication(identity))


@router.post('/context-notes', status_code=201)
def context(body: ContextCreate, db: Session = Depends(get_db)):
    return call(lambda: EmotionRepository(db).add_context(body))


@router.patch('/context-notes/{identity}')
def update_context(identity: str, body: ContextUpdate, db: Session = Depends(get_db)):
    return call(lambda: EmotionRepository(db).update_context(identity, body.status))


@router.get('/auction-source')
def auction_source(db: Session = Depends(get_db)):
    return LifecycleRepository(db).source_config()


@router.put('/auction-source')
def save_auction_source(body: AuctionSettings, db: Session = Depends(get_db)):
    return LifecycleRepository(db).save_source(body)


@router.get('/publications/{identity}/lifecycle')
def lifecycle(identity: str, db: Session = Depends(get_db)):
    return call(lambda: LifecycleRepository(db).view(identity))


@router.post('/publications/{identity}/monitor')
def monitor(identity: str, body: MonitorCommand, db: Session = Depends(get_db)):
    return call(lambda: LifecycleRepository(db).set_monitor(identity, body.enabled))


@router.post('/reviews', status_code=202)
async def review(body: ReviewCreate):
    def create(repository):
        row, created = LifecycleRepository(repository.db).create_review(body)
        return run_dto(row), created
    try:
        row, created = await emotion_runner.write(create)
    except WorkspaceError as exc:
        raise api_error(409 if str(exc)=='analysis_running' else 400, 'emotion_'+str(exc), str(exc)) from None
    if created: emotion_runner.start(row['id'])
    return row


@router.get('/session-validation/{trade_date}')
def session_validation(trade_date: date, db: Session = Depends(get_db)):
    from .session_validation import SessionValidationRepository
    return call(lambda: SessionValidationRepository(db).view(trade_date.isoformat()))


@router.put('/session-validation/{trade_date}')
def arm_session_validation(trade_date: date, body: MonitorCommand, db: Session = Depends(get_db)):
    from .session_validation import SessionValidationRepository
    return call(lambda: SessionValidationRepository(db).arm(trade_date.isoformat(),body.enabled))
