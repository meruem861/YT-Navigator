#!/usr/bin/env bash
# Install the APK on a running emulator, launch it and check the bundled server serves the main pages.
# Usage: android/smoke-test.sh path/to/app.apk
set -euo pipefail

APK="$1"
OUT="${SMOKE_OUT:-smoke-test-output}"
mkdir -p "$OUT"

adb install -r "$APK"
adb logcat -c
adb shell am start -n com.ytnavigator.app/.MainActivity

PORT=""
for _ in $(seq 1 150); do
    PORT="$(adb logcat -d | grep -o 'listening on 127.0.0.1:[0-9]*' | tail -1 | cut -d: -f2 || true)"
    [ -n "$PORT" ] && break
    sleep 2
done

if [ -z "$PORT" ]; then
    echo "Server did not start. Recent log:"
    adb logcat -d > "$OUT/logcat.txt"
    grep -iE "python|YTNavigator|AndroidRuntime|chaquopy" "$OUT/logcat.txt" | tail -200
    exit 1
fi
echo "Server is listening on port $PORT"

adb forward tcp:18000 "tcp:$PORT"
status=0
for path in / /query/ /chatbot/ /settings/ /static/images/youtube-favicon.ico; do
    code="$(curl -s -o "$OUT/page.html" -w '%{http_code}' "http://127.0.0.1:18000$path")"
    echo "GET $path -> $code"
    [ "$code" = "200" ] || status=1
done
curl -s "http://127.0.0.1:18000/settings/" | grep -oE "Using the built-in key|Not set" | sort | uniq -c

sleep 5
adb exec-out screencap -p > "$OUT/screenshot.png"
adb logcat -d > "$OUT/logcat.txt"
exit $status
