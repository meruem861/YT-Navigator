#!/usr/bin/env bash
# Install the APK on a running emulator, launch it and check the bundled server serves the main pages.
# Usage: android/smoke-test.sh path/to/app.apk
set -uo pipefail

APK="$1"
OUT="${SMOKE_OUT:-smoke-test-output}"
mkdir -p "$OUT"

save_outputs() {
    adb exec-out screencap -p > "$OUT/screenshot.png" || true
    adb logcat -d > "$OUT/logcat.txt" || true
}

fail() {
    echo "FAILED: $1"
    save_outputs
    echo "--- Python / app log ---"
    grep -E "python\.(stdout|stderr)|YTNavigator|AndroidRuntime" "$OUT/logcat.txt" | tail -150
    exit 1
}

adb install -r "$APK" || fail "install"
adb logcat -c
adb shell am start -n com.ytnavigator.app/.MainActivity || fail "launch"

PORT=""
for _ in $(seq 1 150); do
    PORT="$(adb logcat -d 2>/dev/null | grep -o 'listening on 127.0.0.1:[0-9]*' | tail -1 | cut -d: -f2)"
    [ -n "$PORT" ] && break
    sleep 2
done
[ -n "$PORT" ] || fail "server did not start"
echo "Server is listening on port $PORT"

adb forward tcp:18000 "tcp:$PORT" > /dev/null || fail "port forward"
for path in / /query/ /chatbot/ /settings/ /static/images/youtube-favicon.ico; do
    code="$(curl -s -o "$OUT/last-page.html" -w '%{http_code}' "http://127.0.0.1:18000$path")"
    echo "GET $path -> $code"
    [ "$code" = "200" ] || fail "GET $path returned $code"
done
echo "Settings page: $(curl -s http://127.0.0.1:18000/settings/ | grep -oE 'Using the built-in key|Not set' | sort | uniq -c | tr -s ' \n' ' ')"

sleep 5
save_outputs
echo "Smoke test passed"
