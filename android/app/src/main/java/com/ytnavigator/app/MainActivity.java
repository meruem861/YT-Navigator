package com.ytnavigator.app;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Shows the YT Navigator web app served by Termux on http://127.0.0.1:8000.
 *
 * <p>On launch it asks Termux (through its RUN_COMMAND service) to start the server if it is not
 * already running, waits for it, then loads it. Links to other sites (YouTube) open externally.
 */
public class MainActivity extends Activity {

    private static final String SERVER_URL = "http://127.0.0.1:8000/";
    private static final String TERMUX_PACKAGE = "com.termux";
    private static final String RUN_COMMAND_PERMISSION = "com.termux.permission.RUN_COMMAND";
    private static final String START_COMMAND = "/data/data/com.termux/files/usr/bin/ytnav";
    private static final int PERMISSION_REQUEST = 1;
    private static final int STARTUP_TIMEOUT_SECONDS = 90;

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private WebView webView;
    private boolean waiting;

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
        if (waiting) {
            return;
        }
        waiting = true;
        showStatus("Starting YT Navigator…", "Waiting for the server running in Termux.", false);
        executor.execute(() -> {
            if (!isServerUp()) {
                mainHandler.post(this::requestServerStart);
                for (int i = 0; i < STARTUP_TIMEOUT_SECONDS && !isServerUp(); i++) {
                    sleepOneSecond();
                }
            }
            boolean up = isServerUp();
            mainHandler.post(() -> {
                waiting = false;
                if (up) {
                    webView.loadUrl(SERVER_URL);
                } else {
                    showStatus(
                            "Server not running",
                            "Open Termux and run <code>ytnav</code>, then tap Retry.<br><br>"
                                    + "First time? Follow the setup steps in <code>mobile/README.md</code>.",
                            true);
                }
            });
        });
    }

    /** Ask Termux to run the start script in the background. */
    private void requestServerStart() {
        if (!isTermuxInstalled()) {
            return;
        }
        if (checkSelfPermission(RUN_COMMAND_PERMISSION) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[] {RUN_COMMAND_PERMISSION}, PERMISSION_REQUEST);
            return;
        }
        Intent intent = new Intent("com.termux.RUN_COMMAND");
        intent.setClassName(TERMUX_PACKAGE, "com.termux.app.RunCommandService");
        intent.putExtra("com.termux.RUN_COMMAND_PATH", START_COMMAND);
        intent.putExtra("com.termux.RUN_COMMAND_BACKGROUND", true);
        try {
            startForegroundService(intent);
        } catch (RuntimeException e) {
            // Termux refused (allow-external-apps not enabled) or is unavailable; the user can start it manually.
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == PERMISSION_REQUEST
                && grantResults.length > 0
                && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            requestServerStart();
        }
    }

    private boolean isTermuxInstalled() {
        try {
            getPackageManager().getPackageInfo(TERMUX_PACKAGE, 0);
            return true;
        } catch (PackageManager.NameNotFoundException e) {
            return false;
        }
    }

    private static boolean isServerUp() {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(SERVER_URL + "login/").openConnection();
            connection.setConnectTimeout(1000);
            connection.setReadTimeout(2000);
            return connection.getResponseCode() > 0;
        } catch (Exception e) {
            return false;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private static void sleepOneSecond() {
        try {
            Thread.sleep(1000);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private void showStatus(String title, String message, boolean showActions) {
        String actions = showActions
                ? "<p><a class='btn' href='ytnav://retry'>Retry</a>"
                        + "<a class='btn alt' href='ytnav://termux'>Open Termux</a></p>"
                : "<div class='spinner'></div>";
        String html = "<html><head><meta name='viewport' content='width=device-width, initial-scale=1'>"
                + "<style>"
                + "body{font-family:sans-serif;background:#0f0f0f;color:#f1f1f1;display:flex;flex-direction:column;"
                + "justify-content:center;align-items:center;height:100vh;margin:0;padding:0 24px;text-align:center}"
                + "h1{font-size:22px;color:#ff4e45}p{color:#aaa;line-height:1.5}code{color:#fff}"
                + ".btn{display:inline-block;margin:8px;padding:12px 22px;border-radius:22px;background:#ff0000;"
                + "color:#fff;text-decoration:none;font-weight:bold}.alt{background:#272727}"
                + ".spinner{width:36px;height:36px;border:4px solid #333;border-top-color:#ff0000;border-radius:50%;"
                + "animation:s 1s linear infinite}@keyframes s{to{transform:rotate(360deg)}}"
                + "</style></head><body><h1>" + title + "</h1><p>" + message + "</p>" + actions + "</body></html>";
        webView.loadDataWithBaseURL(null, html, "text/html", "utf-8", null);
    }

    private void openTermux() {
        Intent intent = getPackageManager().getLaunchIntentForPackage(TERMUX_PACKAGE);
        if (intent != null) {
            startActivity(intent);
        } else {
            openExternally(Uri.parse("https://f-droid.org/packages/com.termux/"));
        }
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
                if ("termux".equals(uri.getHost())) {
                    openTermux();
                } else {
                    startServerAndLoad();
                }
                return true;
            }
            String host = uri.getHost();
            if ("127.0.0.1".equals(host) || "localhost".equals(host)) {
                return false;
            }
            openExternally(uri);
            return true;
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            // The server stopped (e.g. Android killed Termux): go back to the startup screen
            if (request.isForMainFrame()) {
                startServerAndLoad();
            }
        }
    }
}
