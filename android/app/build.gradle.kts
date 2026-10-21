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

    // Ключ подписи хранится в секретах GitHub (VARIS_KEYSTORE_B64, VARIS_KEY_PASSWORD),
    // workflow кладёт его в android/app/varis.keystore перед сборкой. Без ключа
    // (сборка PR) APK подписывается отладочным ключом и в релиз не попадает.
    val keystore = file("varis.keystore")
    val varisPassword = System.getenv("VARIS_KEY_PASSWORD")
    val hasReleaseKey = keystore.exists() && !varisPassword.isNullOrEmpty()

    signingConfigs {
        if (hasReleaseKey) {
            create("varis") {
                storeFile = keystore
                storePassword = varisPassword
                keyAlias = "varis"
                keyPassword = varisPassword
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName(if (hasReleaseKey) "varis" else "debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
