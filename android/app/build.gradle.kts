plugins {
    id("com.android.application")
}

// Номер версии = номер сборки в GitHub Actions, чтобы новый APK ставился поверх старого.
val buildNumber = (System.getenv("GITHUB_RUN_NUMBER") ?: "1").toInt()

android {
    namespace = "kz.varis.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "kz.varis.app"
        minSdk = 26
        targetSdk = 34
        versionCode = buildNumber
        versionName = "1.$buildNumber"
    }

    // Постоянный ключ из репозитория: иначе каждая сборка подписана новым ключом
    // и телефон отказывается ставить обновление поверх. Приложение личное, не для Google Play.
    signingConfigs {
        create("varis") {
            storeFile = file("varis.keystore")
            storePassword = "varis-app"
            keyAlias = "varis"
            keyPassword = "varis-app"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("varis")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
