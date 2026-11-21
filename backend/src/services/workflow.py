import hashlib
import uuid

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select

from src.config.settings import cache, engine
from src.constants.workflow import MAX_ATTEMPTS, LEASE_SECONDS, Status
from src.models.tables import audit, cases, evidence, runs
from src.services import domain
from src.utils.encoding import canonical
from src.utils.time import utc_time


def log(conn, actor, action, reference, *, case_id=None, run_id=None, evidence_id=None):
    conn.execute(audit.insert().values(actor=actor, action=action, reference=str(reference),
                 case_id=case_id, run_id=run_id, evidence_id=evidence_id, created_at=utc_time()))


def recent(table):
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(select(table).order_by(table.c.id.desc()).limit(100)).mappings()]


def found(conn, table, identity):
    row = conn.execute(select(table).where(table.c.id == identity)).mappings().first()
    if row is None:
        raise HTTPException(404, '找不到该记录')
    return dict(row)


def snapshot_digest(payload):
    return hashlib.sha256(canonical(payload)).hexdigest()


def report_digest(report):
    return hashlib.sha256(canonical(report)).hexdigest()


# The frozen payload stays server-side; list responses only carry its digest.
RUN_COLUMNS = (
    runs.c.id, runs.c.case_id, runs.c.status, runs.c.owner, runs.c.version,
    runs.c.attempts, runs.c.payload_digest, runs.c.started_at, runs.c.finished_at,
    runs.c.created_at, runs.c.error,
)


def run_summary(conn, run_id):
    row = conn.execute(select(*RUN_COLUMNS).where(runs.c.id == run_id)).mappings().first()
    if row is None:
        raise HTTPException(404, '找不到该记录')
    return dict(row)


def make_case(title, payload, actor):
    title, payload = _case_input(title, payload)
    with engine.begin() as conn:
        case_id = conn.execute(cases.insert().values(slug=uuid.uuid4().hex, title=title, payload=payload,
                               author=actor, created_at=utc_time())).inserted_primary_key[0]
        log(conn, actor, 'create_case', case_id, case_id=case_id)
        return found(conn, cases, case_id)


def update_case(case_id, title, payload, actor):
    """Change a case without touching runs already queued against its old snapshot."""
    title, payload = _case_input(title, payload)
    with engine.begin() as conn:
        current = conn.execute(select(cases).where(cases.c.id == case_id).with_for_update()).mappings().first()
        if current is None:
            raise HTTPException(404, '找不到该记录')
        conn.execute(cases.update().where(cases.c.id == case_id).values(
            title=title, payload=payload))
        log(conn, actor, 'update_case', case_id, case_id=case_id)
        return found(conn, cases, case_id)


def _case_input(title, payload):
    title = title.strip()
    if not title:
        raise HTTPException(422, '档案名称不能为空')
    try:
        if len(canonical(payload)) > 512 * 1024:
            raise ValueError('业务输入超过 512 KiB')
        if callable(getattr(domain, 'validate', None)):
            domain.validate(payload)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from None
    return title, payload


def enqueue(case_id, actor):
    """Freeze the current ledger snapshot on a new run.

    A repeated submit for the same case and snapshot returns the run that is
    already queued, running or complete, so a double click can neither change
    the input nor publish a second evidence record.
    """
    with engine.begin() as conn:
        case = conn.execute(select(cases).where(cases.c.id == case_id).with_for_update()).mappings().first()
        if case is None:
            raise HTTPException(404, '找不到该记录')
        payload = case['payload']
        digest = snapshot_digest(payload)
        existing = conn.execute(select(*RUN_COLUMNS).where(
            runs.c.case_id == case_id, runs.c.payload_digest == digest,
            runs.c.status.in_((Status.QUEUED, Status.RUNNING, Status.COMPLETE)),
        ).order_by(runs.c.id.desc())).mappings().first()
        if existing is not None:
            result = dict(existing)
            result['reused'] = True
        else:
            version = conn.execute(select(func.max(runs.c.version))
                                   .where(runs.c.case_id == case_id)).scalar_one_or_none() or 0
            run_id = conn.execute(runs.insert().values(
                case_id=case_id, status=Status.QUEUED, owner=actor, payload=payload,
                payload_digest=digest, version=version + 1, attempts=0,
                created_at=utc_time())).inserted_primary_key[0]
            log(conn, actor, 'enqueue', run_id, case_id=case_id, run_id=run_id)
            result = run_summary(conn, run_id)
            result['reused'] = False
    try:
        cache.lpush('worker:wake', 'queued')
        cache.ltrim('worker:wake', 0, 99)
    except Exception:
        # The durable database queue is polled even if Redis is temporarily unavailable.
        pass
    return result


def list_runs():
    statement = select(*RUN_COLUMNS, cases.c.title.label('case_title'),
                       evidence.c.id.label('evidence_id'),
                       evidence.c.reviewed_at.label('evidence_reviewed_at'))\
        .select_from(runs.join(cases, cases.c.id == runs.c.case_id)
                     .outerjoin(evidence, evidence.c.run_id == runs.c.id))\
        .order_by(runs.c.id.desc()).limit(100)
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(statement).mappings()]


def list_evidence():
    statement = select(evidence, runs.c.case_id, runs.c.status.label('run_status'),
                       runs.c.attempts.label('run_attempts'), runs.c.error.label('run_error'),
                       runs.c.version.label('run_version'),
                       runs.c.payload_digest.label('run_payload_digest'),
                       cases.c.title.label('case_title'))\
        .select_from(evidence.join(runs, runs.c.id == evidence.c.run_id)
                     .join(cases, cases.c.id == runs.c.case_id))\
        .order_by(evidence.c.id.desc()).limit(100)
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(statement).mappings()]


def _claimable():
    return or_(runs.c.status == Status.QUEUED,
               and_(runs.c.status == Status.RUNNING,
                    or_(runs.c.lease_expires_at.is_(None),
                        runs.c.lease_expires_at < utc_time())))


def claim():
    """Lease one durable job; expired leases become retries under a new token."""
    with engine.begin() as conn:
        candidates = conn.execute(select(runs).where(_claimable()).order_by(runs.c.id).limit(10)
                                  .with_for_update(skip_locked=True)).mappings().all()
        for run in candidates:
            attempts = run['attempts'] or 0
            if run['status'] == Status.RUNNING and attempts >= MAX_ATTEMPTS:
                _abandon(conn, run, '执行中断且重试次数已达上限，请修正输入后重新提交。')
                continue
            if run['payload'] is None or run['payload_digest'] != snapshot_digest(run['payload']):
                _abandon(conn, run, '排队快照缺失或摘要不一致，已停止执行。')
                continue
            attempts += 1
            token = str(uuid.uuid4())
            conn.execute(runs.update().where(runs.c.id == run['id']).values(
                started_at=utc_time(), status=Status.RUNNING, attempt_token=token, attempts=attempts,
                lease_expires_at=utc_time(LEASE_SECONDS), error=None))
            if attempts > 1:
                log(conn, 'worker', 'retry', run['id'], case_id=run['case_id'], run_id=run['id'])
            return run['id'], token, run['payload'], run['case_id']
        return None


def _abandon(conn, run, message):
    conn.execute(runs.update().where(runs.c.id == run['id']).values(
        status=Status.FAILED, finished_at=utc_time(), lease_expires_at=None, error=message))
    log(conn, 'worker', 'failed', run['id'], case_id=run['case_id'], run_id=run['id'])


def renew(run_id, token):
    """Extend the lease. False means the attempt was superseded and must stop."""
    with engine.begin() as conn:
        count = conn.execute(runs.update().where(
            runs.c.id == run_id, runs.c.attempt_token == token, runs.c.status == Status.RUNNING)
            .values(lease_expires_at=utc_time(LEASE_SECONDS))).rowcount
    return bool(count)


def finish(run_id, token, result=None, error=None):
    """Write the outcome only for the attempt that still owns the lease."""
    with engine.begin() as conn:
        run = conn.execute(select(runs).where(runs.c.id == run_id).with_for_update()).mappings().first()
        if run is None or run['status'] != Status.RUNNING or run['attempt_token'] != token:
            return None
        digest = None
        evidence_id = None
        if result is not None and error is None:
            digest = report_digest(result)
            evidence_id = conn.execute(evidence.insert().values(
                run_id=run_id, report=result, digest=digest, payload_digest=run['payload_digest'],
                version=run['version'], attempt=run['attempts'], created_at=utc_time(),
            )).inserted_primary_key[0]
        status = Status.FAILED if error else Status.COMPLETE
        conn.execute(runs.update().where(
            runs.c.id == run_id, runs.c.attempt_token == token, runs.c.status == Status.RUNNING)
            .values(status=status, finished_at=utc_time(), lease_expires_at=None, error=error))
        log(conn, 'worker', status.value, run_id, case_id=run['case_id'], run_id=run_id,
            evidence_id=evidence_id)
        return evidence_id


def fail_attempt(run_id, token, message, retry=True):
    """Record a failed attempt; retryable failures stay queued for a new lease."""
    with engine.begin() as conn:
        run = conn.execute(select(runs).where(runs.c.id == run_id).with_for_update()).mappings().first()
        if run is None or run['status'] != Status.RUNNING or run['attempt_token'] != token:
            return None
        attempts = run['attempts'] or 0
        if retry and attempts < MAX_ATTEMPTS:
            conn.execute(runs.update().where(runs.c.id == run_id).values(
                status=Status.QUEUED, attempt_token=None, lease_expires_at=None, error=message))
            log(conn, 'worker', 'retry', run_id, case_id=run['case_id'], run_id=run_id)
            return True
        conn.execute(runs.update().where(runs.c.id == run_id).values(
            status=Status.FAILED, finished_at=utc_time(), lease_expires_at=None, error=message))
        log(conn, 'worker', 'failed', run_id, case_id=run['case_id'], run_id=run_id)
        return False


def review(identity, note, actor):
    """Sign evidence once; only a verified, complete run can be signed."""
    note = note.strip()
    if not note:
        raise HTTPException(422, '复核意见不能为空')
    with engine.begin() as conn:
        row = conn.execute(select(evidence).where(evidence.c.id == identity)
                           .with_for_update()).mappings().first()
        if row is None:
            raise HTTPException(404, '找不到该记录')
        run = conn.execute(select(runs).where(runs.c.id == row['run_id'])).mappings().first()
        if run is None or run['status'] != Status.COMPLETE:
            raise HTTPException(409, '该证据对应的执行尚未成功完成，不能签署')
        if row['reviewed_at'] is not None:
            raise HTTPException(409, '该证据已经复核')
        if not row['payload_digest'] or row['attempt'] is None:
            raise HTTPException(409, '该证据缺少排队快照追溯信息，不能签署')
        if (row['payload_digest'] != run['payload_digest']
                or row['attempt'] != run['attempts']):
            raise HTTPException(409, '证据版本与执行快照不一致，不能签署')
        if report_digest(row['report']) != row['digest']:
            raise HTTPException(409, '证据校验失败，不能签署')
        conn.execute(evidence.update().where(
            evidence.c.id == identity, evidence.c.reviewed_at.is_(None))
            .values(review_note=note, reviewer=actor, reviewed_at=utc_time()))
        log(conn, actor, 'review', identity, case_id=run['case_id'], run_id=run['id'],
            evidence_id=identity)
        return _evidence_document(conn, identity)


def signed_document(identity, actor):
    """Return publishable evidence only after the review signature is committed."""
    with engine.begin() as conn:
        row = conn.execute(select(evidence).where(evidence.c.id == identity)
                           .with_for_update()).mappings().first()
        if row is None:
            raise HTTPException(404, '找不到该记录')
        run = conn.execute(select(runs).where(runs.c.id == row['run_id'])).mappings().first()
        if run is None or run['status'] != Status.COMPLETE:
            raise HTTPException(409, '该证据对应的执行尚未成功完成')
        if row['reviewed_at'] is None:
            raise HTTPException(409, '证据尚未复核签署，暂不可下载')
        if (row['payload_digest'] and run['payload_digest']
                and row['payload_digest'] != run['payload_digest']):
            raise HTTPException(409, '证据校验失败，暂不可下载')
        if row['attempt'] is not None and run['attempts'] is not None \
                and row['attempt'] != run['attempts']:
            raise HTTPException(409, '证据校验失败，暂不可下载')
        if report_digest(row['report']) != row['digest']:
            raise HTTPException(409, '证据校验失败，暂不可下载')
        document = _evidence_document(conn, identity)
        log(conn, actor, 'download', identity, case_id=run['case_id'], run_id=run['id'],
            evidence_id=identity)
        return document


def _evidence_document(conn, identity):
    statement = select(evidence, runs.c.case_id, runs.c.status.label('run_status'),
                       runs.c.attempts.label('run_attempts'), runs.c.error.label('run_error'),
                       runs.c.version.label('run_version'), runs.c.payload_digest.label('run_payload_digest'),
                       runs.c.finished_at.label('run_finished_at'),
                       cases.c.title.label('case_title'))\
        .select_from(evidence.join(runs, runs.c.id == evidence.c.run_id)
                     .join(cases, cases.c.id == runs.c.case_id))\
        .where(evidence.c.id == identity)
    row = conn.execute(statement).mappings().first()
    if row is None:
        raise HTTPException(404, '找不到该记录')
    row = dict(row)
    return {
        'evidence': {
            'id': row['id'], 'run_id': row['run_id'], 'report': row['report'],
            'digest': row['digest'], 'payload_digest': row['payload_digest'],
            'version': row['version'], 'attempt': row['attempt'],
            'created_at': row['created_at'], 'reviewer': row['reviewer'],
            'review_note': row['review_note'], 'reviewed_at': row['reviewed_at'],
        },
        'run': {
            'id': row['run_id'], 'status': row['run_status'], 'attempts': row['run_attempts'],
            'version': row['run_version'], 'payload_digest': row['run_payload_digest'],
            'error': row['run_error'], 'finished_at': row['run_finished_at'],
        },
        'case': {'id': row['case_id'], 'title': row['case_title']},
        'lineage': {
            'case_id': row['case_id'], 'run_id': row['run_id'], 'evidence_id': row['id'],
            'snapshot_digest': row['payload_digest'], 'report_digest': row['digest'],
            'evidence_version': row['version'], 'evidence_attempt': row['attempt'],
        },
    }
