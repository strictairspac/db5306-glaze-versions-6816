import logging
from pathlib import Path
from threading import Event, Thread
from time import monotonic, sleep

from src.config.settings import ARTIFACTS, cache, engine
from src.constants.workflow import LEASE_RENEW_SECONDS
from src.services.domain import solve
from src.services.workflow import claim, fail_attempt, finish, renew

HEARTBEAT = Path(ARTIFACTS) / 'worker-heartbeat'
LIVENESS_SECONDS = 2


def heartbeat(stop, run_id, token):
    """Touch worker liveness and keep the job lease alive while it is held."""
    last_renewal = monotonic()
    while not stop.wait(LIVENESS_SECONDS):
        HEARTBEAT.touch()
        if monotonic() - last_renewal < LEASE_RENEW_SECONDS:
            continue
        last_renewal = monotonic()
        try:
            if not renew(run_id, token):
                # Another attempt holds the lease now; discard this result.
                stop.set()
                return
        except Exception:
            logging.exception('Lease renewal failed: %s', run_id)


def work():
    HEARTBEAT.unlink(missing_ok=True)
    while True:
        try:
            job = claim()
            HEARTBEAT.touch()
            if not job:
                cache.brpop('worker:wake', timeout=1)
                continue
            run_id, token, payload, _case_id = job
            stop = Event()
            thread = Thread(target=heartbeat, args=(stop, run_id, token), daemon=True)
            thread.start()
            try:
                result = solve(payload, engine)
                if not stop.is_set():
                    finish(run_id, token, result=result)
            except (ValueError, KeyError, TypeError) as exc:
                if not stop.is_set():
                    fail_attempt(run_id, token, str(exc)[:500], retry=False)
            except Exception:
                logging.exception('Domain run failed: %s', run_id)
                if not stop.is_set():
                    fail_attempt(run_id, token, '后台执行失败，稍后自动重试；如持续失败请检查 worker 日志。')
            finally:
                stop.set()
                thread.join()
        except Exception:
            logging.exception('Worker loop failure')
            sleep(2)


if __name__ == '__main__':
    work()
