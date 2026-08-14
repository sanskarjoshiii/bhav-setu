#!/usr/bin/env bash
# Route smoke tests: every page must return 200 AND render its key content.
BASE=http://localhost:3000
pass=0
fail=0

check() {
  local path="$1" want="$2" label="$3"
  local body code
  body=$(curl -s -w "\n%{http_code}" "$BASE$path")
  code=$(printf '%s' "$body" | tail -1)
  if [ "$code" != "200" ]; then
    printf '  FAIL  %-14s HTTP %s\n' "$path" "$code"
    fail=$((fail + 1))
    return
  fi
  if printf '%s' "$body" | grep -qF "$want"; then
    printf '  ok    %-14s %s\n' "$path" "$label"
    pass=$((pass + 1))
  else
    printf '  FAIL  %-14s missing: %s\n' "$path" "$want"
    fail=$((fail + 1))
  fi
}

echo "PAGES"
check /             "actually take home"        "hero renders"
check /dashboard    "mandi prices — Nashik"    "district board renders"
check /advisor      "What should I do with"     "advisor renders"
check /compare      "highest price is not"      "comparison renders"
check /community    "Share a truck"             "pooling renders"
check /history      "Everything you have asked" "history renders"
check /chat         "like you would ask a"      "chat renders"
check /login        "one-time code"             "login form renders"
check /signup       "Three questions"           "signup wizard renders"
check /lots         "What you have in store"    "lots render"
check /reports      "What you told us you got"  "reports render"
check /transparency "took home"                 "transparency renders"
check /accuracy     "How wrong are we"          "accuracy renders"
check /about        "How it works"              "about renders"
check /help         "Questions farmers"         "help renders"

echo
echo "NAVIGATION"
check /             "/dashboard"  "nav links to dashboard"
check /             "/community"  "nav links to community"
check /             "/history"    "nav links to history"

echo
echo "SEEDED CONTENT"
check /community    "Ramesh Pawar"       "pool members listed"
check /community    "tel:+91"            "call links present"
check /community    "wa.me"              "whatsapp links present"
check /dashboard    "Pomegranate"        "fruits present"
check /dashboard    "Ahmadnagar"         "districts present"
check /login        "never share your number" "privacy note shown"
check /history      "Pomegranate"        "seeded history entries"

echo
echo "NO PROTOTYPE TELLS"
for p in / /dashboard /advisor /compare /community /history /chat /login /signup /about; do
  body=$(curl -s "$BASE$p")
  bad=""
  printf '%s' "$body" | grep -qiE "seeded|demo data|demo build|demo account|cost_model.yaml|config file|Showing seeded" && bad="prototype wording"
  # strip hrefs first: the WhatsApp deep link legitimately carries the bot number
  printf '%s' "$body" | sed 's/href="[^"]*"//g' | grep -qE "123456|9673338564" && bad="$bad credentials"
  if [ -n "$bad" ]; then
    printf '  FAIL  %-14s %s
' "$p" "$bad"
    fail=$((fail + 1))
  else
    printf '  ok    %-14s clean
' "$p"
    pass=$((pass + 1))
  fi
done

echo
echo "404"
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/no-such-page")
if [ "$code" = "404" ]; then
  printf '  ok    %-14s returns 404\n' "/no-such-page"
  pass=$((pass + 1))
else
  printf '  FAIL  %-14s expected 404, got %s\n' "/no-such-page" "$code"
  fail=$((fail + 1))
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "  ✅ all $pass route checks passed"
else
  echo "  $pass passed, $fail FAILED"
fi
exit $((fail > 0))
