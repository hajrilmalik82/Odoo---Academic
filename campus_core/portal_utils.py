import functools
import logging

from psycopg2 import IntegrityError, OperationalError
from werkzeug.exceptions import HTTPException

from odoo import _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

_FLASH_ERROR_KEY = 'campus_portal_error'
_FLASH_SUCCESS_KEY = 'campus_portal_success'

# PostgreSQL SQLSTATE codes that Odoo's HTTP dispatcher retries automatically
# on a fresh REPEATABLE READ snapshot (serialization_failure, deadlock_detected,
# lock_not_available). Swallowing them inside a controller breaks concurrency
# control and leaves the PostgreSQL transaction aborted.
_PG_CONCURRENCY_RETRY_CODES = frozenset(('40001', '40P01', '55P03'))


def redirect_with_error(url, message):
    """Store an error flash message in the user's session and redirect cleanly."""
    request.session[_FLASH_ERROR_KEY] = str(message)
    return request.redirect(url)


def redirect_with_success(url, message):
    """Store a success flash message in the user's session and redirect cleanly."""
    request.session[_FLASH_SUCCESS_KEY] = str(message)
    return request.redirect(url)


def pop_flash_messages():
    """Consume one-shot portal flash banners from the user's session."""
    return {
        'error': request.session.pop(_FLASH_ERROR_KEY, None),
        'success': request.session.pop(_FLASH_SUCCESS_KEY, None),
    }


def report_errors_to(url_for, logger=None, integrity_message=None):
    """Wrap a portal POST route in a savepoint and convert errors into redirects.

    Concurrency errors and Werkzeug HTTP exceptions are explicitly re-raised so
    Odoo's transaction retry loop and standard HTTP error handling keep working.
    """
    log = logger or logging.getLogger(__name__)

    def decorator(route):
        @functools.wraps(route)
        def wrapper(self, *args, **kwargs):
            try:
                with request.env.cr.savepoint():
                    return route(self, *args, **kwargs)
            except HTTPException:
                raise
            except OperationalError as error:
                if getattr(error, 'pgcode', None) in _PG_CONCURRENCY_RETRY_CODES:
                    raise
                log.exception(
                    "%s failed with database error for user %s",
                    route.__name__,
                    request.env.user.login,
                )
                return redirect_with_error(url_for(*args, **kwargs), _("A system error occurred."))
            except (ValidationError, UserError) as error:
                message = error.args[0] if error.args else _("The action could not be completed.")
                return redirect_with_error(url_for(*args, **kwargs), message)
            except AccessError:
                log.warning(
                    "%s denied access for user %s",
                    route.__name__,
                    request.env.user.login,
                )
                return redirect_with_error(
                    url_for(*args, **kwargs),
                    _("You do not have permission to perform this action."),
                )
            except IntegrityError:
                log.warning(
                    "%s hit IntegrityError for user %s",
                    route.__name__,
                    request.env.user.login,
                    exc_info=True,
                )
                msg = integrity_message or _(
                    "That class or action conflicts with an existing registration rule."
                )
                return redirect_with_error(url_for(*args, **kwargs), msg)
            except Exception:
                log.exception(
                    "%s failed for user %s", route.__name__, request.env.user.login,
                )
                return redirect_with_error(url_for(*args, **kwargs), _("A system error occurred."))

        return wrapper

    return decorator
