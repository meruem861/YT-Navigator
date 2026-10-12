# YT Navigator Android app

A WebView app that runs the YT Navigator Django server inside the APK (Python bundled with
[Chaquopy](https://chaquo.com/chaquopy/)) and shows it full screen. User guide: [../mobile/README.md](../mobile/README.md).

How it works:
- `app/build.gradle.kts` copies the repository's `app/` and `yt_navigator/` packages into the APK and installs
  the Python packages listed in `app/requirements.txt`.
- At launch, `MainActivity` calls `yt_navigator.android.start()`, which migrates the SQLite database in the app's
  private storage and serves the site with uvicorn on a free `127.0.0.1` port.
- Built-in API keys come from the `DEFAULT_GROQ_API_KEY` / `DEFAULT_COHERE_API_KEY` environment variables at
  build time; users can override them in the app's Settings page.

## Building

GitHub Actions builds it (workflow `Build Android APK`), runs `smoke-test.sh` on an emulator, and uploads
`yt-navigator-apk` to the run's Artifacts.

Locally, with JDK 17, the Android SDK (platform 34), Gradle 8.9+ and Python 3.12 on the PATH:

```bash
cd android
DEFAULT_GROQ_API_KEY=... DEFAULT_COHERE_API_KEY=... gradle assembleDebug
# -> app/build/outputs/apk/debug/app-debug.apk
```
