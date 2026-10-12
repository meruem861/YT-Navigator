# 📱 YT Navigator on Android

YT Navigator is a single Android app. The whole server (Django + SQLite) is bundled inside the APK with
[Chaquopy](https://chaquo.com/chaquopy/) and runs on the phone. Only the AI calls go to the internet:
**Groq** (chat) and **Cohere** (search).

## For clients: install and use

1. Download `yt-navigator.apk` (you receive it from the app owner).
2. Tap it and allow *Install unknown apps* when Android asks.
3. Open **YT Navigator**. There is no account to create.
4. **Home**: paste a YouTube channel link, then scan its videos (start with ~10).
5. **Chat**: ask questions about the videos; answers link to the exact moments.
   **Search**: find the passages that talk about a topic.

The app comes with built-in API keys. To use your own free keys instead, open **Settings** and paste a
[Groq key](https://console.groq.com/keys) and/or a [Cohere key](https://dashboard.cohere.com/api-keys).

Requirements: Android 8 or newer, an internet connection, ~150 MB of free storage.

## For the app owner: build the APK

The APK is built by GitHub Actions (`.github/workflows/android-apk.yml`) on every push that changes the app.

1. **Built-in keys**: in the GitHub repository open *Settings → Secrets and variables → Actions* and add two
   repository secrets: `GROQ_API_KEY` and `COHERE_API_KEY`. Without them the app still works, but each client
   has to enter keys in Settings.
2. **Build**: push a change, or open *Actions → Build Android APK → Run workflow*.
3. **Download**: open the finished run → *Artifacts* → `yt-navigator-apk` (a zip containing `yt-navigator.apk`).
   The run also installs the APK on an Android emulator and checks that the app starts (`smoke-test-output`
   has a screenshot and the log).

> ⚠️ Keys built into an APK can be extracted by anyone who has the file, and all clients share your quota.
> Use keys with spending limits, rotate them if the APK leaks, and share the APK only with your clients.

Each build is signed with a temporary debug key, so installing a new build over an old one can fail with
"App not installed": uninstall the old version first (this deletes its data). Ask if you want a permanent
signing key for smooth updates or a Play Store release.

## Troubleshooting

- **"Could not start YT Navigator"**: tap Retry. If it keeps failing, send the message shown on screen.
- **Scanning finds 0 transcripts**: the videos have no captions, or YouTube is temporarily blocking transcript
  requests. Try again later or on another network (Wi-Fi vs mobile data).
- **Chat says a model was not found**: Groq retires models from time to time. Update `INSTANT_LLM` /
  `POWERFUL_LLM` in `yt_navigator/settings.py` (see https://console.groq.com/docs/models) and rebuild.
- **Chat or search says a key is missing or invalid**: add or replace the key in Settings.

## Alternative for developers: run the server in Termux

`mobile/termux-setup.sh` installs the same server in [Termux](https://f-droid.org/packages/com.termux/)
(`bash mobile/termux-setup.sh`, then `ytnav`, then open http://127.0.0.1:8000 in Chrome). This is handy for
trying changes on the phone without rebuilding the APK.
