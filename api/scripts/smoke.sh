#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8787}"
TOKEN="${ADMIN_TOKEN:-local-dev-token}"
PLAYGRAPH="${PLAYGRAPH:-$HOME/Developer/GitHub/playgraph}"
INSTALL_A="11111111-1111-4111-8111-111111111111"
INSTALL_B="22222222-2222-4222-8222-222222222222"
ARCHETYPE="modern-eldrazi"

cd "$(dirname "$0")/.."

for name in modern-eldrazi modern-boros-energy; do
  ADMIN_TOKEN="$TOKEN" node scripts/publish.mjs "$BASE" "$name" "$PLAYGRAPH/primers/$name.md" "$PLAYGRAPH/dist/primers/$name.json"
done

echo "--- unauthorized publish"
curl -s -w ' [%{http_code}]\n' -X PUT "$BASE/v1/primers/$ARCHETYPE" -H 'Content-Type: application/json' -d '{}'

echo "--- GET primer (headers + summary)"
TMP="$(mktemp)"
curl -s -D - -o "$TMP" "$BASE/v1/primers/$ARCHETYPE" | grep -iE '^(HTTP|cache-control|access-control-allow-origin)'
node -e 'const r=JSON.parse(require("fs").readFileSync(process.argv[1],"utf8"));console.log(JSON.stringify({title:r.primer.title,author:r.primer.author,written:r.primer.written,updated:r.primer.updated,sections:r.primer.sections.length,version:r.version,ratings:r.ratings}))' "$TMP"
rm -f "$TMP"

echo "--- GET missing"
curl -s -w ' [%{http_code}]\n' "$BASE/v1/primers/nope"

echo "--- vote up (A), down (B)"
curl -s -X PUT "$BASE/v1/primers/$ARCHETYPE/rating" -H 'Content-Type: application/json' -d "{\"install\":\"$INSTALL_A\",\"value\":1}"; echo
curl -s -X PUT "$BASE/v1/primers/$ARCHETYPE/rating" -H 'Content-Type: application/json' -d "{\"install\":\"$INSTALL_B\",\"value\":-1}"; echo

echo "--- GET rating as A and B"
curl -s "$BASE/v1/primers/$ARCHETYPE/rating?install=$INSTALL_A"; echo
curl -s "$BASE/v1/primers/$ARCHETYPE/rating?install=$INSTALL_B"; echo

echo "--- B flips to up, A clears"
curl -s -X PUT "$BASE/v1/primers/$ARCHETYPE/rating" -H 'Content-Type: application/json' -d "{\"install\":\"$INSTALL_B\",\"value\":1}"; echo
curl -s -X PUT "$BASE/v1/primers/$ARCHETYPE/rating" -H 'Content-Type: application/json' -d "{\"install\":\"$INSTALL_A\",\"value\":0}"; echo

echo "--- validation"
curl -s -w ' [%{http_code}]\n' -X PUT "$BASE/v1/primers/$ARCHETYPE/rating" -H 'Content-Type: application/json' -d '{"install":"nope","value":1}'
curl -s -w ' [%{http_code}]\n' -X PUT "$BASE/v1/primers/$ARCHETYPE/rating" -H 'Content-Type: application/json' -d "{\"install\":\"$INSTALL_A\",\"value\":5}"
curl -s -w ' [%{http_code}]\n' -X PUT "$BASE/v1/primers/$ARCHETYPE/rating" -H 'Content-Type: application/json' -d "{\"install\":\"$INSTALL_A\",\"value\":1,\"pad\":\"$(head -c 1100 /dev/zero | tr '\0' x)\"}"

echo "--- list"
curl -s "$BASE/v1/primers"; echo
