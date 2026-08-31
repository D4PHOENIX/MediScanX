plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.example.mediscanx"
    compileSdk = 36
    ndkVersion = flutter.ndkVersion

    // --- FIXED FOR KOTLIN DSL ---
    androidResources {
        noCompress += "tflite"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_17.toString()
    }

    defaultConfig {
        applicationId = "com.example.mediscanx"
        minSdk = 24

        // --- BYPASSING KOTLIN STRICT NULL-CHECKS ---
        targetSdk = (flutter.targetSdkVersion as? Int) ?: 34
        versionCode = (flutter.versionCode as? Int) ?: 1
        versionName = (flutter.versionName as? String) ?: "1.0"
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

flutter {
    source = "../.."
}

configurations.all {
    resolutionStrategy {
        // These versions are stable and compatible with AGP 8.7.0
        force ("androidx.activity:activity:1.9.3")
        force ("androidx.activity:activity-ktx:1.9.3")
        force ("androidx.core:core:1.13.1")
        force ("androidx.core:core-ktx:1.13.1")
        force ("androidx.lifecycle:lifecycle-common:2.8.2")
    }
}

dependencies {
    implementation("org.tensorflow:tensorflow-lite-select-tf-ops:+")
}