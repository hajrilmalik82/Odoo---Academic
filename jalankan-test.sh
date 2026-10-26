#!/usr/bin/env bash
#
# Upgrade the five campus modules and run their tests.
#
#   ./jalankan-test.sh                 against the default database
#   ./jalankan-test.sh nama-database   against another one
#
# Two flags are easy to forget and both have bitten this project:
#
#   --i18n-overwrite   Odoo does NOT replace a translation that already exists
#                      in the database. Without this, editing an id.po changes
#                      nothing and the old wording stays on screen - including
#                      on printed transcripts.
#
#   --http-port        the tests need a port of their own. Using the default
#                      collides with a server you left running, and the run
#                      dies with "Address already in use" rather than a result.
#
#   --db-filter        odoo.conf pins one database name. The HttpCase tests log
#                      in over real HTTP, and a session for a database the
#                      filter rejects is thrown out on the next request - so
#                      every route test fails on any database but that one,
#                      with "dbfilter rejects it" buried in the log.
set -euo pipefail

DB="${1:-academic-19}"
ODOO_DIR="${ODOO_DIR:-$HOME/odoo-dev/odoo-19}"
PYTHON="${PYTHON:-$ODOO_DIR/venv-19/bin/python}"
PORT="${TEST_PORT:-8099}"
MODULES="campus_core,campus_website,campus_employees,campus_pmb,campus_portal"
LOG="$(mktemp -t campus-test-XXXXXX.log)"

echo "database : $DB"
echo "modul    : $MODULES"
echo "log      : $LOG"
echo

set +e
"$PYTHON" "$ODOO_DIR/odoo-bin" \
    -c "$ODOO_DIR/odoo.conf" \
    -d "$DB" \
    -u "$MODULES" \
    --test-enable \
    --i18n-overwrite \
    --stop-after-init \
    --http-port="$PORT" \
    --db-filter="^${DB}\$" \
    --log-level=info > "$LOG" 2>&1
STATUS=$?
set -e

grep -E "odoo\.tests\.stats" "$LOG" | sed 's/.*odoo.tests.stats: /  /' || true
echo

# The result line names its database, and a run can emit more than one - an
# earlier line about a different database with zero tests matched a naive grep
# and reported green over a red run.
RESULT="$(grep -E "odoo\.tests\.result" "$LOG" | grep -F "database '$DB'" | tail -1)"

if [ -z "$RESULT" ]; then
    echo "MERAH: no test result for database '$DB'. The run probably failed before the tests."
    tail -20 "$LOG"
    exit 1
fi

if echo "$RESULT" | grep -qE "0 failed, 0 error"; then
    echo "$RESULT" | sed 's/.*odoo.tests.result: /HIJAU: /'
    exit 0
fi

echo "$RESULT" | sed 's/.*odoo.tests.result: /MERAH: /'
echo "Yang gagal:"
grep -E "(ERROR|FAIL): Test" "$LOG" | sed 's/.*: /  /' || echo "  (tidak ada baris test yang gagal - lihat log, mungkin gagal saat upgrade)"
echo
echo "Log lengkap: $LOG"
exit "${STATUS:-1}"
