plugins {
    id("com.android.application")
}

android {
    namespace = "com.ytnavigator.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.ytnavigator.app"
        minSdk = 26
        // 34 keeps the classic (non edge-to-edge) layout on Android 15
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
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
