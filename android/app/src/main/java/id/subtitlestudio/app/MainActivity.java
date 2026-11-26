package id.subtitlestudio.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.DownloadManager;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

public class MainActivity extends Activity {

    private static final String PREF_NAME = "subtitle_studio_config";
    private static final String KEY_SERVER_URL = "server_url";
    private static final String DEFAULT_SERVER_URL = "http://127.0.0.1:8765";
    private static final int REQ_FILE_CHOOSER = 1001;

    private WebView webView;
    private View splashLayout;
    private ProgressBar progressBar;
    private TextView txtStatus;
    private TextView txtSubStatus;
    private LinearLayout btnContainer;
    private Button btnRetry;
    private Button btnChangeServer;

    private ValueCallback<Uri[]> filePathCallback;
    private String serverUrl;
    private long lastBackPressTime = 0;
    private boolean serverReady = false;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        webView = findViewById(R.id.webView);
        splashLayout = findViewById(R.id.splashLayout);
        progressBar = findViewById(R.id.progressBar);
        txtStatus = findViewById(R.id.txtStatus);
        txtSubStatus = findViewById(R.id.txtSubStatus);
        btnContainer = findViewById(R.id.btnContainer);
        btnRetry = findViewById(R.id.btnRetry);
        btnChangeServer = findViewById(R.id.btnChangeServer);

        SharedPreferences prefs = getSharedPreferences(PREF_NAME, MODE_PRIVATE);
        serverUrl = prefs.getString(KEY_SERVER_URL, DEFAULT_SERVER_URL);

        setupWebView();

        btnRetry.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                checkAndConnectServer();
            }
        });

        btnChangeServer.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showServerConfigDialog();
            }
        });

        checkAndConnectServer();
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void setupWebView() {
        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(true);
        s.setAllowContentAccess(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(true);
        s.setSupportZoom(true);
        s.setBuiltInZoomControls(true);
        s.setDisplayZoomControls(false);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);

        CookieManager cookieManager = CookieManager.getInstance();
        cookieManager.setAcceptCookie(true);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            cookieManager.setAcceptThirdPartyCookies(webView, true);
        }

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                String url = request.getUrl().toString();
                if (url.startsWith("http://") || url.startsWith("https://")) {
                    return false;
                }
                try {
                    Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                    startActivity(intent);
                    return true;
                } catch (Exception e) {
                    return false;
                }
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    showErrorState("Gagal memuat antarmuka Subtitle Studio.");
                }
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView webView, ValueCallback<Uri[]> filePathCallback,
                                             WebChromeClient.FileChooserParams fileChooserParams) {
                if (MainActivity.this.filePathCallback != null) {
                    MainActivity.this.filePathCallback.onReceiveValue(null);
                }
                MainActivity.this.filePathCallback = filePathCallback;

                Intent intent = new Intent(Intent.ACTION_GET_CONTENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType("*/*");
                String[] mimeTypes = {"audio/*", "video/*", "text/*", "application/octet-stream"};
                intent.putExtra(Intent.EXTRA_MIME_TYPES, mimeTypes);

                try {
                    startActivityForResult(Intent.createChooser(intent, "Pilih Berkas Media / Subtitle"), REQ_FILE_CHOOSER);
                    return true;
                } catch (Exception e) {
                    MainActivity.this.filePathCallback = null;
                    Toast.makeText(MainActivity.this, "Tidak dapat membuka pengelola berkas", Toast.LENGTH_SHORT).show();
                    return false;
                }
            }
        });

        webView.setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String url, String userAgent, String contentDisposition,
                                        String mimeType, long contentLength) {
                try {
                    String fileName = URLUtil.guessFileName(url, contentDisposition, mimeType);
                    DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
                    request.setMimeType(mimeType);
                    request.setDescription("Mengunduh dari Subtitle Studio");
                    request.setTitle(fileName);
                    request.allowScanningByMediaScanner();
                    request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                    request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, fileName);

                    DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
                    if (dm != null) {
                        dm.enqueue(request);
                        Toast.makeText(MainActivity.this, "Mengunduh " + fileName + " ke folder Download…", Toast.LENGTH_LONG).show();
                    }
                } catch (Exception e) {
                    // Fallback browser download
                    try {
                        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                        startActivity(intent);
                    } catch (Exception ignored) {
                        Toast.makeText(MainActivity.this, "Gagal memulai unduhan", Toast.LENGTH_SHORT).show();
                    }
                }
            }
        });
    }

    private void checkAndConnectServer() {
        progressBar.setVisibility(View.VISIBLE);
        btnContainer.setVisibility(View.GONE);
        txtStatus.setText(R.string.loading_msg);
        txtSubStatus.setText("Memeriksa " + serverUrl + "…");

        new Thread(new Runnable() {
            @Override
            public void run() {
                boolean ok = false;
                try {
                    URL u = new URL(serverUrl + "/api/health");
                    HttpURLConnection conn = (HttpURLConnection) u.openConnection();
                    conn.setConnectTimeout(2500);
                    conn.setReadTimeout(2500);
                    conn.setRequestMethod("GET");
                    int code = conn.getResponseCode();
                    ok = (code >= 200 && code < 400);
                    conn.disconnect();
                } catch (Exception ignored) {
                    ok = false;
                }

                final boolean ready = ok;
                mainHandler.post(new Runnable() {
                    @Override
                    public void run() {
                        if (ready) {
                            serverReady = true;
                            splashLayout.setVisibility(View.GONE);
                            webView.setVisibility(View.VISIBLE);
                            webView.loadUrl(serverUrl);
                        } else {
                            showErrorState("Server belum aktif di " + serverUrl);
                        }
                    }
                });
            }
        }).start();
    }

    private void showErrorState(String errorMsg) {
        serverReady = false;
        progressBar.setVisibility(View.GONE);
        btnContainer.setVisibility(View.VISIBLE);
        txtStatus.setText(errorMsg);
        txtSubStatus.setText("Pastikan server berjalan di Termux:\ncd ~/subtitle-studio && ./run.sh");
    }

    private void showServerConfigDialog() {
        AlertDialog.Builder builder = new AlertDialog.Builder(this);
        builder.setTitle("Alamat Server Subtitle Studio");
        builder.setMessage("Masukkan alamat server lokal atau jaringan:");

        final EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setText(serverUrl);
        builder.setView(input);

        builder.setPositiveButton("Simpan", new DialogInterface.OnClickListener() {
            @Override
            public void onClick(DialogInterface dialog, int which) {
                String val = input.getText().toString().trim();
                if (!val.isEmpty()) {
                    if (!val.startsWith("http://") && !val.startsWith("https://")) {
                        val = "http://" + val;
                    }
                    serverUrl = val;
                    SharedPreferences prefs = getSharedPreferences(PREF_NAME, MODE_PRIVATE);
                    prefs.edit().putString(KEY_SERVER_URL, serverUrl).apply();
                    checkAndConnectServer();
                }
            }
        });

        builder.setNegativeButton("Batal", null);
        builder.show();
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_FILE_CHOOSER) {
            if (filePathCallback == null) return;
            Uri[] results = null;
            if (resultCode == RESULT_OK && data != null) {
                if (data.getDataString() != null) {
                    results = new Uri[]{Uri.parse(data.getDataString())};
                } else if (data.getClipData() != null) {
                    int count = data.getClipData().getItemCount();
                    results = new Uri[count];
                    for (int i = 0; i < count; i++) {
                        results[i] = data.getClipData().getItemAt(i).getUri();
                    }
                }
            }
            filePathCallback.onReceiveValue(results);
            filePathCallback = null;
        }
    }

    @Override
    public void onBackPressed() {
        if (serverReady && webView.getVisibility() == View.VISIBLE && webView.canGoBack()) {
            webView.goBack();
            return;
        }
        long now = System.currentTimeMillis();
        if (now - lastBackPressTime < 2000) {
            super.onBackPressed();
        } else {
            lastBackPressTime = now;
            Toast.makeText(this, "Tekan sekali lagi untuk keluar", Toast.LENGTH_SHORT).show();
        }
    }
}
