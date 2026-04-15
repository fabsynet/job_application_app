"""Phase 5 SMTP sender — async aiosmtplib wrapper with structured failure.

All :mod:`aiosmtplib` exceptions are wrapped into :class:`SubmissionSendError`
with a stable ``error_class`` attribute so Plan 05-05's failure-suppression
table can hash on a deterministic key without importing aiosmtplib types.
"""
from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage

import aiosmtplib
import structlog

log = structlog.get_logger(__name__)


class SubmissionSendError(Exception):
    """Wraps any :mod:`aiosmtplib` failure with a stable ``error_class`` name.

    The ``error_class`` attribute is a plain string identifier suitable
    for the Plan 05-05 failure-signature hash. The original exception is
    preserved as :attr:`cause` and chained via ``raise ... from exc`` so
    tracebacks stay intact.
    """

    def __init__(
        self,
        *,
        error_class: str,
        message: str,
        cause: Exception | None = None,
    ):
        super().__init__(message)
        self.error_class = error_class
        self.message = message
        self.cause = cause


@dataclass
class SmtpConfig:
    """Everything :func:`send_via_smtp` needs to open a connection.

    :attr:`timeout` is a hard per-call wall clock (seconds). aiosmtplib
    applies this to every connection phase (connect, STARTTLS, AUTH,
    DATA) so a stuck server cannot hang the pipeline forever.
    """

    host: str
    port: int
    username: str
    password: str
    timeout: float = 30.0


async def send_via_smtp(msg: EmailMessage, cfg: SmtpConfig) -> None:
    """Send an :class:`EmailMessage` via :func:`aiosmtplib.send`.

    Transport selection is implicit from :attr:`SmtpConfig.port`:

    * ``587`` — STARTTLS (standard submission port)
    * ``465`` — implicit TLS (SMTPS)
    * anything else — neither (plain connection, dev/test only)

    Any aiosmtplib failure is wrapped in :class:`SubmissionSendError` with
    a stable ``error_class`` identifier. The caller (Plan 05-04) picks a
    classification bucket from the identifier; nothing else should catch
    aiosmtplib types directly.
    """
    try:
        await aiosmtplib.send(
            msg,
            hostname=cfg.host,
            port=cfg.port,
            username=cfg.username,
            password=cfg.password,
            start_tls=(cfg.port == 587),
            use_tls=(cfg.port == 465),
            timeout=cfg.timeout,
        )
    except aiosmtplib.SMTPAuthenticationError as exc:
        raise SubmissionSendError(
            error_class="SMTPAuthenticationError",
            message=str(exc),
            cause=exc,
        ) from exc
    except aiosmtplib.SMTPRecipientsRefused as exc:
        raise SubmissionSendError(
            error_class="SMTPRecipientsRefused",
            message=str(exc),
            cause=exc,
        ) from exc
    except aiosmtplib.SMTPServerDisconnected as exc:
        raise SubmissionSendError(
            error_class="SMTPServerDisconnected",
            message=str(exc),
            cause=exc,
        ) from exc
    except aiosmtplib.SMTPTimeoutError as exc:
        raise SubmissionSendError(
            error_class="SMTPTimeoutError",
            message=str(exc),
            cause=exc,
        ) from exc
    except aiosmtplib.SMTPException as exc:
        # Catch-all for any other aiosmtplib error — keep the concrete
        # exception class name so the suppression table still gets a
        # stable key (e.g. "SMTPConnectError", "SMTPHeloError").
        raise SubmissionSendError(
            error_class=type(exc).__name__,
            message=str(exc),
            cause=exc,
        ) from exc


__all__ = ["SmtpConfig", "SubmissionSendError", "send_via_smtp"]
