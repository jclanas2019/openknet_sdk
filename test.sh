#!/usr/bin/env bash
set -euo pipefail

# Functional black-box test suite for OpenKNet.
# It does not use pytest. It exercises the installed CLI and HTTP API as an external user.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_DIR="$(mktemp -d -t openknet-functional-XXXXXX)"
PORT="${OPENKNET_TEST_PORT:-8765}"
API_PID=""

cleanup() {
  if [[ -n "${API_PID}" ]]; then
    kill "${API_PID}" >/dev/null 2>&1 || true
  fi
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

section() {
  printf '\n==> %s\n' "$1"
}

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

assert_json_file() {
  local file="$1"
  python - "$file" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as f:
    json.load(f)
PY
}

run_ok() {
  local label="$1"
  shift
  "$@" >"${TMP_DIR}/${label}.out" 2>"${TMP_DIR}/${label}.err" || {
    cat "${TMP_DIR}/${label}.err" >&2
    fail "command failed: $*"
  }
}

run_fail() {
  local label="$1"
  shift
  if "$@" >"${TMP_DIR}/${label}.out" 2>"${TMP_DIR}/${label}.err"; then
    fail "command should have failed but succeeded: $*"
  fi
}

section "Install package"
python -m pip install -e "${ROOT_DIR}" >/dev/null

section "CLI availability"
openknet --help >/dev/null
[[ "$(openknet version)" == "0.1.6" ]] || fail "unexpected openknet version"

section "Create isolated workspace"
cd "${TMP_DIR}"
DOCS="${ROOT_DIR}/examples/support/docs"
SCHEMA="${ROOT_DIR}/examples/support/schema.yaml"

section "Initialize project"
run_ok init openknet init support-demo --schema "${SCHEMA}"
assert_json_file "${TMP_DIR}/init.out"
[[ -f ".openknet/support-demo/schema.yaml" ]] || fail "schema.yaml was not created"
[[ -f ".openknet/support-demo/store.json" ]] || fail "store.json was not created"

section "Ingest documents using --project"
run_ok ingest_flag openknet ingest "${DOCS}" --project support-demo
assert_json_file "${TMP_DIR}/ingest_flag.out"
python - "${TMP_DIR}/ingest_flag.out" <<'PY'
import json, sys
obj = json.load(open(sys.argv[1], encoding='utf-8'))
assert obj["documents_added"] == 2, obj
assert obj["documents_total"] == 2, obj
assert obj["chunks_total"] >= 2, obj
PY

section "Build knowledge network"
run_ok build_flag openknet build --project support-demo
assert_json_file "${TMP_DIR}/build_flag.out"
python - "${TMP_DIR}/build_flag.out" <<'PY'
import json, sys
obj = json.load(open(sys.argv[1], encoding='utf-8'))
assert obj["entities"] >= 8, obj
assert obj["relations"] >= 4, obj
assert obj["evidence"] >= 4, obj
PY

section "Validate persisted store semantics"
python - ".openknet/support-demo/store.json" <<'PY'
import json, sys
store = json.load(open(sys.argv[1], encoding='utf-8'))
entities = {(e['type'], e['name']): e['id'] for e in store['entities']}
required_entities = [
    ('Customer', 'ACME'),
    ('Customer', 'Globex'),
    ('Product', 'Portal X'),
    ('Product', 'Billing API'),
    ('Component', 'AuthService'),
    ('Component', 'BillingService'),
    ('Error', 'error 503'),
    ('Error', 'timeout'),
    ('Incident', 'INC-1001'),
    ('Incident', 'INC-1002'),
]
missing = [x for x in required_entities if x not in entities]
assert not missing, missing

relations = {(r['source_id'], r['type'], r['target_id']): r for r in store['relations']}
expected_relations = [
    (entities[('Component', 'AuthService')], 'causes', entities[('Error', 'error 503')]),
    (entities[('Component', 'BillingService')], 'causes', entities[('Error', 'timeout')]),
    (entities[('Product', 'Portal X')], 'depends_on', entities[('Component', 'AuthService')]),
    (entities[('Product', 'Billing API')], 'depends_on', entities[('Component', 'BillingService')]),
]
missing_rels = [x for x in expected_relations if x not in relations]
assert not missing_rels, missing_rels

evidence_by_id = {e['id']: e for e in store['evidence']}
chunk_ids = {c['id'] for c in store['chunks']}
for rel in relations.values():
    assert rel['evidence_ids'], rel
    for eid in rel['evidence_ids']:
        assert eid in evidence_by_id, (eid, rel)
        assert evidence_by_id[eid]['chunk_id'] in chunk_ids, evidence_by_id[eid]
        assert evidence_by_id[eid]['quote'].strip(), evidence_by_id[eid]
PY

section "Rank behavior"
run_ok rank_flag openknet rank "login error" --project support-demo
assert_json_file "${TMP_DIR}/rank_flag.out"
python - "${TMP_DIR}/rank_flag.out" <<'PY'
import json, sys
obj = json.load(open(sys.argv[1], encoding='utf-8'))
names = [r['entity']['name'] for r in obj['results']]
assert 'AuthService' in names, names
assert 'error 503' in names or 'login error' in names, names
assert obj['results'][0]['score'] > 0, obj
PY

section "Ask behavior"
run_ok ask_flag openknet ask "what components are related to login errors?" --project support-demo
assert_json_file "${TMP_DIR}/ask_flag.out"
python - "${TMP_DIR}/ask_flag.out" <<'PY'
import json, sys
obj = json.load(open(sys.argv[1], encoding='utf-8'))
assert 'Related entities:' in obj['answer'], obj
names = [r['entity']['name'] for r in obj['results']]
assert 'AuthService' in names, names
PY

section "Path behavior"
run_ok path_flag openknet path "AuthService" "error 503" --project support-demo
assert_json_file "${TMP_DIR}/path_flag.out"
python - "${TMP_DIR}/path_flag.out" <<'PY'
import json, sys
obj = json.load(open(sys.argv[1], encoding='utf-8'))
assert obj['paths'], obj
assert any('causes' in p['relations'] for p in obj['paths']), obj
assert any(p['evidence_ids'] for p in obj['paths']), obj
PY

section "Positional PROJECT syntax"
run_ok rank_pos openknet rank "billing timeout" support-demo
run_ok ask_pos openknet ask "what causes timeout?" support-demo
run_ok path_pos openknet path "BillingService" "timeout" support-demo
assert_json_file "${TMP_DIR}/rank_pos.out"
assert_json_file "${TMP_DIR}/ask_pos.out"
assert_json_file "${TMP_DIR}/path_pos.out"

section "Negative CLI cases"
run_fail missing_project openknet rank "login error"
grep -E "Project is required|Missing|Usage" "${TMP_DIR}/missing_project.err" >/dev/null || fail "missing project error message not useful"
run_fail disagree openknet rank "login error" support-demo --project other-project
grep -E "disagree|Invalid value|BadParameter" "${TMP_DIR}/disagree.err" >/dev/null || fail "conflicting project error message not useful"
run_fail no_path openknet ingest "${TMP_DIR}/does-not-exist" --project support-demo
grep -E "not found|No such file|FileNotFound" "${TMP_DIR}/no_path.err" >/dev/null || fail "missing path error message not useful"
run_fail no_project openknet build --project unknown-project
grep -E "Project not found|not found|FileNotFound" "${TMP_DIR}/no_project.err" >/dev/null || fail "missing project error message not useful"

section "HTTP API black-box behavior"
python -m uvicorn openknet.api:app --host 127.0.0.1 --port "${PORT}" >"${TMP_DIR}/api.out" 2>"${TMP_DIR}/api.err" &
API_PID="$!"
python - "${PORT}" <<'PY'
import sys, time, urllib.request
port = sys.argv[1]
url = f"http://127.0.0.1:{port}/health"
last = None
for _ in range(50):
    try:
        with urllib.request.urlopen(url, timeout=0.3) as r:
            if r.status == 200:
                sys.exit(0)
    except Exception as exc:
        last = exc
        time.sleep(0.1)
raise SystemExit(f"API did not become ready: {last}")
PY
python - "${PORT}" <<'PY'
import json, sys, urllib.parse, urllib.request
port = sys.argv[1]

def get(path, params=None):
    qs = urllib.parse.urlencode(params or {})
    url = f"http://127.0.0.1:{port}{path}" + (f"?{qs}" if qs else "")
    with urllib.request.urlopen(url, timeout=3) as r:
        assert r.status == 200, r.status
        return json.loads(r.read().decode())

health = get('/health')
assert health['status'] == 'ok', health
rank = get('/rank', {'project': 'support-demo', 'query': 'login error'})
assert any(x['entity']['name'] == 'AuthService' for x in rank['results']), rank
ask = get('/ask', {'project': 'support-demo', 'question': 'what components are related to login errors?'})
assert 'AuthService' in json.dumps(ask), ask
path = get('/path', {'project': 'support-demo', 'source': 'AuthService', 'target': 'error 503'})
assert path['paths'], path
PY

section "Rebuild idempotency"
run_ok build_again openknet build --project support-demo
python - ".openknet/support-demo/store.json" <<'PY'
import json, sys
store = json.load(open(sys.argv[1], encoding='utf-8'))
rel_ids = [r['id'] for r in store['relations']]
ev_ids = [e['id'] for e in store['evidence']]
assert len(rel_ids) == len(set(rel_ids)), 'duplicate relation ids'
assert len(ev_ids) == len(set(ev_ids)), 'duplicate evidence ids'
PY

printf '\nAll functional black-box tests completed.\n'
