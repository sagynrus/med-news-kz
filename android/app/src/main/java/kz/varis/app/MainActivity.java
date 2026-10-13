package kz.varis.app;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/**
 * Экран приложения — веб-страница из assets/index.html. Она сама скачивает
 * news.json и razbor.json с GitHub Pages и хранит избранное в localStorage телефона.
 */
public class MainActivity extends Activity {
    private WebView web;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        web = new WebView(this);
        web.setBackgroundColor(0xFF0C0C11);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(true);
        s.setAllowFileAccessFromFileURLs(true);
        s.setTextZoom(100);
        web.addJavascriptInterface(new Bridge(), "Varis");
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri uri = req.getUrl();
                if ("file".equals(uri.getScheme())) return false;
                openExternal(uri.toString());
                return true;
            }
        });
        setContentView(web);
        if (state != null) web.restoreState(state);
        else web.loadUrl("file:///android_asset/index.html");
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    protected void onResume() {
        super.onResume();
        web.evaluateJavascript("window.onAppResume && onAppResume()", null);
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        // Сначала закрываем открытую карточку или возвращаемся на «Ленту», потом выходим.
        web.evaluateJavascript("window.goBack ? goBack() : false", result -> {
            if (!"true".equals(result)) finish();
        });
    }

    private void openExternal(String url) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        } catch (Exception ignored) {
        }
    }

    private class Bridge {
        @JavascriptInterface
        public void open(String url) {
            runOnUiThread(() -> openExternal(url));
        }

        @JavascriptInterface
        public void share(String text) {
            runOnUiThread(() -> {
                Intent i = new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text);
                startActivity(Intent.createChooser(i, "Поделиться"));
            });
        }
    }
}
