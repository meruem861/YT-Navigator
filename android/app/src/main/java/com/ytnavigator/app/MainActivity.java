package com.ytnavigator.app;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.Html;
import android.util.Log;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Runs the YT Navigator server (Django, bundled with Chaquopy) inside the app and shows it full screen.
 *
 * <p>Links to other sites (YouTube, API key pages) open in the matching app or the browser.
 */
public class MainActivity extends Activity {

    private static final String TAG = "YTNavigator";

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private WebView webView;
    private String serverUrl;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        webView = new WebView(this);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        webView.setWebViewClient(new LocalOnlyClient());
        setContentView(webView);

        startServerAndLoad();
    }

    private void startServerAndLoad() {
        showStatus("Starting YT Navigator…", "This takes a few seconds the first time.", false);
        executor.execute(() -> {
            try {
                if (!Python.isStarted()) {
                    Python.start(new AndroidPlatform(this));
                }
                int port = Python.getInstance()
                        .getModule("yt_navigator.android")
                        .callAttr(
                                "start",
                                getFilesDir().getAbsolutePath(),
                                BuildConfig.DEFAULT_GROQ_API_KEY,
                                BuildConfig.DEFAULT_COHERE_API_KEY)
                        .toInt();
                serverUrl = "http://127.0.0.1:" + port + "/";
                mainHandler.post(() -> webView.loadUrl(serverUrl));
            } catch (Throwable e) {
                Log.e(TAG, "Server failed to start", e);
                String message = Html.escapeHtml(String.valueOf(e.getMessage()));
                mainHandler.post(() -> showStatus("Could not start YT Navigator", message, true));
            }
        });
    }

    private void showStatus(String title, String message, boolean showRetry) {
        String actions = showRetry
                ? "<p><a class='btn' href='ytnav://retry'>Retry</a></p>"
                : "<div class='spinner'></div>";
        String html = "<html><head><meta name='viewport' content='width=device-width, initial-scale=1'>"
                + "<style>"
                + "body{font-family:sans-serif;background:#0f0f0f;color:#f1f1f1;display:flex;flex-direction:column;"
                + "justify-content:center;align-items:center;height:100vh;margin:0;padding:0 24px;text-align:center}"
                + "h1{font-size:22px;color:#ff4e45}p{color:#aaa;line-height:1.5;word-break:break-word}"
                + ".btn{display:inline-block;margin:8px;padding:12px 22px;border-radius:22px;background:#ff0000;"
                + "color:#fff;text-decoration:none;font-weight:bold}"
                + ".spinner{width:36px;height:36px;border:4px solid #333;border-top-color:#ff0000;border-radius:50%;"
                + "animation:s 1s linear infinite}@keyframes s{to{transform:rotate(360deg)}}"
                + "</style></head><body><h1>" + title + "</h1><p>" + message + "</p>" + actions + "</body></html>";
        webView.loadDataWithBaseURL(null, html, "text/html", "utf-8", null);
    }

    private void openExternally(Uri uri) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (ActivityNotFoundException e) {
            // Nothing can open this link
        }
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        executor.shutdownNow();
        webView.destroy();
        super.onDestroy();
    }

    /** Keeps the app on the local server and sends every other link to the right app (YouTube, browser). */
    private class LocalOnlyClient extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            Uri uri = request.getUrl();
            if ("ytnav".equals(uri.getScheme())) {
                startServerAndLoad();
                return true;
            }
            if ("127.0.0.1".equals(uri.getHost())) {
                return false;
            }
            openExternally(uri);
            return true;
        }
    }
}
