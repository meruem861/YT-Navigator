# YT Navigator Android app

A small WebView app that starts the YT Navigator server through Termux and shows it full screen.
Setup and usage: [../mobile/README.md](../mobile/README.md).

## Building

GitHub Actions builds it on every push that touches `android/` (workflow `Build Android APK`);
download `yt-navigator-apk` from the run's Artifacts.

Locally, with JDK 17, the Android SDK (platform 34) and Gradle 8.9+:

```bash
cd android
gradle assembleDebug
# -> app/build/outputs/apk/debug/app-debug.apk
```
