#!/usr/bin/env bash
#
# Upgrade the campus modules and run their tests.
#
#   ./jalankan-test.sh -d academic-19
#   ./jalankan-test.sh -d academic-19 -u campus_core
#   ./jalankan-test.sh -d academic-19 -u campus_core,campus_portal
#
# -d is required on purpose: this script upgrades modules and runs tests, and
# both write to whatever database it is pointed at. A default would sooner or
# later point at the wrong one.
#
# -u narrows the run. Odoo only runs the tests of the modules it installs or
# upgrades, so naming one module turns a four-minute run into a short one. The
# catch is that the other modules' tests then do not run at all - a change in
# campus_core can break campus_portal and this run still says HIJAU. Narrow it
# while you work; run the whole set before you commit.
#
# Three flags are easy to forget and all three have bitten this project:
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
#   --db-filter        the HttpCase tests log in over real HTTP, and a session
#                      for a database the filter rejects is thrown out on the
#                      next request - so every route test fails, with
#                      "dbfilter rejects it" buried in the log.
set -euo pipefail

SEMUA_MODUL="campus_core,campus_website,campus_employees,campus_pmb,campus_portal"

ODOO_DIR="${ODOO_DIR:-$HOME/odoo-dev/odoo-19}"
PYTHON="${PYTHON:-$ODOO_DIR/venv-19/bin/python}"
CONF="${CONF:-$ODOO_DIR/odoo.conf}"
PORT="${TEST_PORT:-8099}"

DB=""
MODULES="$SEMUA_MODUL"

cara_pakai() {
    cat <<PESAN
Pakai: ./jalankan-test.sh -d <database> [-u <modul,modul>]

  -d  database yang dipakai (wajib)
  -u  modul yang di-upgrade dan diuji
      bawaan: semua lima modul
      pilihan: campus_core campus_website campus_employees campus_pmb campus_portal
  -p  port HTTP untuk test (bawaan $PORT)
  -h  tampilkan bantuan ini

Contoh:
  ./jalankan-test.sh -d academic-19
  ./jalankan-test.sh -d academic-19 -u campus_core
PESAN
}

while getopts ":d:u:p:h" opt; do
    case "$opt" in
        d) DB="$OPTARG" ;;
        u) MODULES="$OPTARG" ;;
        p) PORT="$OPTARG" ;;
        h) cara_pakai; exit 0 ;;
        :) echo "Opsi -$OPTARG butuh nilai." >&2; echo >&2; cara_pakai >&2; exit 1 ;;
        \?) echo "Opsi tidak dikenal: -$OPTARG" >&2; echo >&2; cara_pakai >&2; exit 1 ;;
    esac
done
shift $((OPTIND - 1))

# The old version took the database as a bare first argument. Say so plainly
# instead of silently ignoring it and running against nothing.
if [ "$#" -gt 0 ]; then
    echo "Argumen lepas: '$1'" >&2
    echo "Nama database sekarang lewat -d, jadi: ./jalankan-test.sh -d $1" >&2
    exit 1
fi

if [ -z "$DB" ]; then
    echo "-d <database> wajib diisi." >&2
    echo >&2
    cara_pakai >&2
    echo >&2
    echo "Database yang ada:" >&2
    psql -lqtA -F' ' 2>/dev/null | cut -d' ' -f1 | grep -vE '^(template[01]|postgres)$' \
        | sed 's/^/  /' >&2 || echo "  (tidak bisa membaca daftar database)" >&2
    exit 1
fi

# Reject a module name that is not one of ours before handing it to Odoo, which
# would otherwise just log "module not found" and carry on to run nothing.
IFS=',' read -r -a DAFTAR <<< "$MODULES"
for modul in "${DAFTAR[@]}"; do
    case ",$SEMUA_MODUL," in
        *",$modul,"*) ;;
        *) echo "Bukan modul kampus: '$modul'" >&2
           echo "Pilihannya: ${SEMUA_MODUL//,/ }" >&2
           exit 1 ;;
    esac
done

echo "database : $DB"
echo "modul    : $MODULES"

if [ "$MODULES" != "$SEMUA_MODUL" ]; then
    echo "catatan  : hanya modul di atas yang diuji - jalankan tanpa -u sebelum commit"
fi

if ! psql -d "$DB" -tAc "SELECT 1" >/dev/null 2>&1; then
    echo >&2
    echo "Database '$DB' tidak bisa dibuka. Salah nama, atau belum dibuat." >&2
    exit 1
fi

# Refuse to run when a requested module is not installed.
#
# -u updates installed modules and does nothing for the rest, so on a database
# that has never had them Odoo quietly falls back to installing `base` from
# scratch - and with --test-enable that drags in Odoo's own several-hundred
# test suite. The run then takes many minutes and finishes with zero campus
# tests, which looks like a hang rather than a mistake.
BELUM=""
for modul in "${DAFTAR[@]}"; do
    STATE="$(psql -d "$DB" -tAc \
        "SELECT state FROM ir_module_module WHERE name = '$modul'" 2>/dev/null || true)"
    [ "$STATE" = "installed" ] || BELUM="${BELUM:+$BELUM,}$modul"
done

if [ -n "$BELUM" ]; then
    cat >&2 <<PESAN

Belum terpasang di database '$DB': $BELUM

  -u hanya meng-update modul yang sudah ada. Di database kosong, Odoo akan
  memasang base dari nol dan --test-enable ikut menjalankan seluruh test
  bawaan Odoo - lama, dan nol test kampus.

Pasang dulu:

  $PYTHON $ODOO_DIR/odoo-bin -c $CONF -d $DB \\
      -i $BELUM --stop-after-init

Tambahkan --with-demo kalau ingin database berisi kampus contoh.
PESAN
    exit 1
fi

LOG="$(mktemp -t campus-test-XXXXXX.log)"
echo "log      : $LOG"
echo

set +e
"$PYTHON" "$ODOO_DIR/odoo-bin" \
    -c "$CONF" \
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
    echo "MERAH: tidak ada hasil test untuk database '$DB'. Run-nya gagal sebelum test jalan."
    tail -20 "$LOG"
    exit 1
fi

if echo "$RESULT" | grep -qE "0 failed, 0 error"; then
    echo "$RESULT" | sed 's/.*odoo.tests.result: /HIJAU: /'
    exit 0
fi

echo "$RESULT" | sed 's/.*odoo.tests.result: /MERAH: /'
echo "Yang gagal:"
# "FAIL: Subtest Foo.bar (...)" as well as "FAIL: Foo.bar" - a subTest failure
# carries an extra word, and the first version of this grep missed it entirely,
# so a red run reported that it could not name what had failed.
grep -oE "(ERROR|FAIL): (Subtest )?Test[A-Za-z0-9_]*\.[a-z0-9_]+" "$LOG" \
    | sed -E 's/^(ERROR|FAIL): //' | sort -u | sed 's/^/  /' \
    || echo "  (tidak ada baris test yang gagal - lihat log, mungkin gagal saat upgrade)"
echo
echo "Log lengkap: $LOG"
exit "${STATUS:-1}"
