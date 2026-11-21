from enum import StrEnum


class Role(StrEnum):
    OPERATOR = 'operator'
    REVIEWER = 'reviewer'
    VIEWER = 'viewer'


class Status(StrEnum):
    QUEUED = 'queued'
    RUNNING = 'running'
    COMPLETE = 'complete'
    FAILED = 'failed'


# Worker leases and automatic retries. A lease that lapses (crash, restart or
# stalled worker) makes the same durable job claimable again under a new token.
LEASE_SECONDS = 60
LEASE_RENEW_SECONDS = 15
MAX_ATTEMPTS = 3
