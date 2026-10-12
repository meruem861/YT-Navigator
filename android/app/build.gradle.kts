plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

// Built-in API keys, injected at build time (GitHub Actions secrets); users can replace them in Settings.
fun secret(name: String): String = (System.getenv(name) ?: "").replace("\\", "\\\\").replace("\"", "\\\"")

android {
    namespace = "com.ytnavigator.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.ytnavigator.app"
        minSdk = 26
        // 34 keeps the classic (non edge-to-edge) layout on Android 15
        targetSdk = 34
        versionCode = 2
        versionName = "2.0"

        ndk {
            // Phones (arm64) and the x86_64 emulator used by CI
            abiFilters += listOf("arm64-v8a", "x86_64")
        }

        buildConfigField("String", "DEFAULT_GROQ_API_KEY", "\"${secret("DEFAULT_GROQ_API_KEY")}\"")
        buildConfigField("String", "DEFAULT_COHERE_API_KEY", "\"${secret("DEFAULT_COHERE_API_KEY")}\"")
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

// The Django project lives at the repository root; copy it into the APK's Python sources.
val pythonSrcDir = "build/python-src"
val syncPythonSources by tasks.registering(Sync::class) {
    from(rootDir.parentFile) {
        include("app/**", "yt_navigator/**")
        exclude("**/__pycache__/**", "**/*.pyc")
    }
    // Read by yt_navigator/__init__.py for the version shown in the page header
    from(rootDir.parentFile.resolve("version.txt")) {
        into("yt_navigator")
    }
    into(pythonSrcDir)
}

tasks.configureEach {
    if (name != syncPythonSources.name && name.contains("Python")) {
        dependsOn(syncPythonSources)
    }
}

chaquopy {
    defaultConfig {
        version = "3.12"
        pip {
            install("-r", "requirements.txt")
        }
        // Django reads templates, static files and translations from disk
        extractPackages("app", "yt_navigator", "django")
    }
    sourceSets {
        getByName("main") {
            srcDir(pythonSrcDir)
        }
    }
}
