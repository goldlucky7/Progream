package io.github.goldlucky7.photoorganizer

/*
 * 사진 정리 도우미 — 안드로이드 앱 본체.
 *
 * photo_organizer/index.html(웹앱)을 WebView로 그대로 띄우고,
 * 웹에서는 불가능한 세 가지를 네이티브로 대신 해 준다:
 *   1) 갤러리 전체 자동 읽기 (MediaStore 쿼리 — 권한 1회)
 *   2) 폴더 → 갤러리에 진짜 앨범 만들기 (Pictures/<폴더명> 복사)
 *   3) 정리함 → 시스템 확인창 1번으로 휴지통 이동 (30일 보관 후 자동 삭제)
 *
 * 웹앱과의 약속(index.html의 네이티브 브리지 구획과 맞물림):
 *   - window.AndroidNative.getInfo()           → 동기, 환경 정보 JSON 문자열
 *   - window.AndroidNative.call(id, method, paramsJson)
 *       → 비동기. 끝나면 window.__anDone(id, ok, payloadJson문자열) 호출
 *       → 진행률은 window.__anProg(id, done, total)
 *   - 썸네일:  https://appassets.androidplatform.net/thumb/{i|v}/{mediaId}
 *   - 원본:    https://appassets.androidplatform.net/media/{i|v}/{mediaId}
 */

import android.annotation.SuppressLint
import android.app.Activity
import android.content.ContentUris
import android.content.ContentValues
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.util.LruCache
import android.util.Size
import android.webkit.JavascriptInterface
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.webkit.WebViewAssetLoader
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors

class MainActivity : ComponentActivity() {

    private lateinit var webView: WebView
    private val mainHandler = Handler(Looper.getMainLooper())
    private val exec = Executors.newFixedThreadPool(2)

    // 썸네일 JPEG 바이트 캐시 (렌더링 반복 시 재압축 방지)
    private val thumbCache = object : LruCache<String, ByteArray>(24 * 1024 * 1024) {
        override fun sizeOf(key: String, value: ByteArray) = value.size
    }

    private var permPending: (() -> Unit)? = null
    private var trashPending: ((Boolean) -> Unit)? = null
    private var filePathCallback: ValueCallback<Array<Uri>>? = null

    private val permLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
            permPending?.invoke(); permPending = null
        }
    private val trashLauncher =
        registerForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) { res ->
            trashPending?.invoke(res.resultCode == Activity.RESULT_OK); trashPending = null
        }
    private val fileLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { res ->
            val cb = filePathCallback; filePathCallback = null
            cb?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(res.resultCode, res.data))
        }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        webView = WebView(this)
        setContentView(webView)
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)

        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
        }

        val assetLoader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .addPathHandler("/thumb/", ThumbHandler())
            .addPathHandler("/media/", MediaHandler())
            .build()

        webView.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                assetLoader.shouldInterceptRequest(request.url)

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (request.url.host == "appassets.androidplatform.net") return false
                try { startActivity(Intent(Intent.ACTION_VIEW, request.url)) } catch (_: Exception) {}
                return true
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            // 백업 불러오기(<input type=file>)용 파일 선택창
            override fun onShowFileChooser(
                view: WebView?, callback: ValueCallback<Array<Uri>>?, params: FileChooserParams?
            ): Boolean {
                filePathCallback?.onReceiveValue(null)
                filePathCallback = callback
                return try {
                    fileLauncher.launch(params!!.createIntent()); true
                } catch (_: Exception) {
                    filePathCallback = null; false
                }
            }
        }

        webView.addJavascriptInterface(Bridge(), "AndroidNative")

        // 뒤로가기: 웹(뷰어·시트·상세화면)이 먼저 처리하고, 남으면 홈으로 (앱 종료 대신 유지)
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (!::webView.isInitialized) { moveTaskToBack(true); return }
                webView.evaluateJavascript("window.__anBack?window.__anBack():'0'") { r ->
                    if (r != "\"1\"") moveTaskToBack(true)
                }
            }
        })

        webView.loadUrl("https://appassets.androidplatform.net/assets/index.html")
    }

    override fun onResume() {
        super.onResume()
        // 갤러리에서 사진을 찍거나 지우고 돌아온 경우 웹 쪽이 목록을 다시 맞춤
        if (::webView.isInitialized) webView.evaluateJavascript("window.__anResumed&&window.__anResumed()", null)
    }

    override fun onDestroy() {
        exec.shutdown()
        super.onDestroy()
    }

    /* ---------- 권한 ---------- */

    private fun has(p: String) = checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED

    private fun requestList(): Array<String> = when {
        Build.VERSION.SDK_INT >= 34 -> arrayOf(
            android.Manifest.permission.READ_MEDIA_IMAGES,
            android.Manifest.permission.READ_MEDIA_VIDEO,
            android.Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED
        )
        Build.VERSION.SDK_INT >= 33 -> arrayOf(
            android.Manifest.permission.READ_MEDIA_IMAGES,
            android.Manifest.permission.READ_MEDIA_VIDEO
        )
        else -> arrayOf(android.Manifest.permission.READ_EXTERNAL_STORAGE)
    }

    private fun accessState(): JSONObject {
        val full = when {
            Build.VERSION.SDK_INT >= 33 ->
                has(android.Manifest.permission.READ_MEDIA_IMAGES) || has(android.Manifest.permission.READ_MEDIA_VIDEO)
            else -> has(android.Manifest.permission.READ_EXTERNAL_STORAGE)
        }
        // Android 14+: "일부 사진만 허용"을 고른 상태
        val partial = !full && Build.VERSION.SDK_INT >= 34 &&
            has(android.Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
        return JSONObject().put("granted", full || partial).put("partial", partial)
    }

    /* ---------- JS 브리지 ---------- */

    inner class Bridge {
        @JavascriptInterface
        fun getInfo(): String = JSONObject()
            .put("platform", "android")
            .put("ver", BuildConfig.VERSION_NAME)
            .put("sdk", Build.VERSION.SDK_INT)
            .put("thumbTpl", "https://appassets.androidplatform.net/thumb/{mt}/{id}")
            .put("mediaTpl", "https://appassets.androidplatform.net/media/{mt}/{id}")
            .toString()

        @JavascriptInterface
        fun call(id: String, method: String, params: String) {
            val p = try { JSONObject(params) } catch (_: Exception) { JSONObject() }
            when (method) {
                "access" -> done(id, true, accessState())
                "request" -> mainHandler.post {
                    permPending = { done(id, true, accessState()) }
                    try { permLauncher.launch(requestList()) }
                    catch (e: Exception) { permPending = null; fail(id, e) }
                }
                "delete" -> mainHandler.post { doTrash(id, p) }
                "open" -> mainHandler.post { doOpen(id, p) }
                "settings" -> mainHandler.post {
                    try {
                        startActivity(
                            Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                                .setData(Uri.fromParts("package", packageName, null))
                        )
                        done(id, true, JSONObject().put("ok", true))
                    } catch (e: Exception) { fail(id, e) }
                }
                else -> exec.execute {
                    try {
                        when (method) {
                            "list" -> done(id, true, doList())
                            "album" -> done(id, true, doAlbum(id, p))
                            "saveText" -> done(id, true, doSaveText(p))
                            else -> done(id, false, JSONObject().put("error", "unknown: $method"))
                        }
                    } catch (e: Exception) { fail(id, e) }
                }
            }
        }
    }

    private fun done(id: String, ok: Boolean, payload: JSONObject) {
        val js = "window.__anDone&&window.__anDone(" + JSONObject.quote(id) + "," + ok + "," +
            JSONObject.quote(payload.toString()) + ")"
        mainHandler.post { if (::webView.isInitialized) webView.evaluateJavascript(js, null) }
    }

    private fun fail(id: String, e: Exception) = done(id, false, JSONObject().put("error", e.toString()))

    private fun prog(id: String, doneN: Int, total: Int) {
        val js = "window.__anProg&&window.__anProg(" + JSONObject.quote(id) + ",$doneN,$total)"
        mainHandler.post { if (::webView.isInitialized) webView.evaluateJavascript(js, null) }
    }

    /* ---------- 미디어 참조 ---------- */

    // ref = "i:123"(사진) / "v:456"(동영상)
    private fun parseRef(ref: String): Pair<String, Long> {
        val i = ref.indexOf(':')
        return Pair(ref.substring(0, i), ref.substring(i + 1).toLong())
    }

    private fun uriFor(mt: String, id: Long): Uri = ContentUris.withAppendedId(
        if (mt == "v") MediaStore.Video.Media.EXTERNAL_CONTENT_URI
        else MediaStore.Images.Media.EXTERNAL_CONTENT_URI, id
    )

    /* ---------- 갤러리 전체 목록 ---------- */

    private fun doList(): JSONObject {
        val items = JSONArray()
        val uri = MediaStore.Files.getContentUri(MediaStore.VOLUME_EXTERNAL)
        val proj = arrayOf(
            MediaStore.Files.FileColumns._ID,
            MediaStore.Files.FileColumns.MEDIA_TYPE,
            MediaStore.Files.FileColumns.DISPLAY_NAME,
            MediaStore.Files.FileColumns.SIZE,
            MediaStore.Files.FileColumns.DATE_MODIFIED,
            MediaStore.Files.FileColumns.DATE_TAKEN,
            MediaStore.Files.FileColumns.MIME_TYPE,
            MediaStore.Files.FileColumns.WIDTH,
            MediaStore.Files.FileColumns.HEIGHT,
            MediaStore.Files.FileColumns.DURATION,
            MediaStore.Files.FileColumns.BUCKET_DISPLAY_NAME
        )
        val sel = MediaStore.Files.FileColumns.MEDIA_TYPE + " IN (?,?)"
        val args = arrayOf(
            MediaStore.Files.FileColumns.MEDIA_TYPE_IMAGE.toString(),
            MediaStore.Files.FileColumns.MEDIA_TYPE_VIDEO.toString()
        )
        contentResolver.query(uri, proj, sel, args, null)?.use { cur ->
            val iId = cur.getColumnIndexOrThrow(MediaStore.Files.FileColumns._ID)
            val iType = cur.getColumnIndexOrThrow(MediaStore.Files.FileColumns.MEDIA_TYPE)
            val iName = cur.getColumnIndexOrThrow(MediaStore.Files.FileColumns.DISPLAY_NAME)
            val iSize = cur.getColumnIndexOrThrow(MediaStore.Files.FileColumns.SIZE)
            val iMod = cur.getColumnIndexOrThrow(MediaStore.Files.FileColumns.DATE_MODIFIED)
            val iTaken = cur.getColumnIndexOrThrow(MediaStore.Files.FileColumns.DATE_TAKEN)
            val iMime = cur.getColumnIndexOrThrow(MediaStore.Files.FileColumns.MIME_TYPE)
            val iW = cur.getColumnIndexOrThrow(MediaStore.Files.FileColumns.WIDTH)
            val iH = cur.getColumnIndexOrThrow(MediaStore.Files.FileColumns.HEIGHT)
            val iDur = cur.getColumnIndexOrThrow(MediaStore.Files.FileColumns.DURATION)
            val iBucket = cur.getColumnIndexOrThrow(MediaStore.Files.FileColumns.BUCKET_DISPLAY_NAME)
            while (cur.moveToNext()) {
                val size = cur.getLong(iSize)
                val name = cur.getString(iName) ?: continue
                if (size <= 0) continue
                val isVideo = cur.getInt(iType) == MediaStore.Files.FileColumns.MEDIA_TYPE_VIDEO
                items.put(JSONObject()
                    .put("id", cur.getLong(iId))
                    .put("mt", if (isVideo) "v" else "i")
                    .put("name", name)
                    .put("size", size)
                    .put("lm", cur.getLong(iMod) * 1000L)
                    .put("taken", cur.getLong(iTaken))
                    .put("mime", cur.getString(iMime) ?: "")
                    .put("w", cur.getInt(iW))
                    .put("h", cur.getInt(iH))
                    .put("dur", cur.getLong(iDur) / 1000.0)
                    .put("bucket", cur.getString(iBucket) ?: ""))
            }
        }
        return JSONObject().put("items", items)
    }

    /* ---------- 폴더 → 갤러리 앨범 (Pictures/<이름>으로 복사) ---------- */

    private fun doAlbum(id: String, p: JSONObject): JSONObject {
        var name = p.optString("name").replace(Regex("[\\\\/:*?\"<>|]"), "_").trim()
        if (name.isEmpty()) name = "사진정리"
        if (name.length > 40) name = name.substring(0, 40)
        val refs = p.optJSONArray("refs") ?: JSONArray()
        val relPath = "Pictures/$name/"
        var okN = 0; var skipN = 0; var failN = 0
        for (i in 0 until refs.length()) {
            try {
                val (mt, mid) = parseRef(refs.getString(i))
                val srcUri = uriFor(mt, mid)
                var dispName = "photo_$mid" + if (mt == "v") ".mp4" else ".jpg"
                var mime = if (mt == "v") "video/mp4" else "image/jpeg"
                var taken = 0L
                contentResolver.query(
                    srcUri,
                    arrayOf(MediaStore.MediaColumns.DISPLAY_NAME, MediaStore.MediaColumns.MIME_TYPE, MediaStore.MediaColumns.DATE_TAKEN),
                    null, null, null
                )?.use { c ->
                    if (c.moveToFirst()) {
                        c.getString(0)?.let { dispName = it }
                        c.getString(1)?.let { mime = it }
                        taken = c.getLong(2)
                    }
                }
                val col = if (mt == "v") MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
                          else MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
                // 같은 이름이 이미 앨범에 있으면 건너뜀 → 다시 저장해도 중복 복사 없음
                val exists = contentResolver.query(
                    col, arrayOf(MediaStore.MediaColumns._ID),
                    MediaStore.MediaColumns.RELATIVE_PATH + "=? AND " + MediaStore.MediaColumns.DISPLAY_NAME + "=?",
                    arrayOf(relPath, dispName), null
                )?.use { it.count > 0 } ?: false
                if (exists) { skipN++; prog(id, i + 1, refs.length()); continue }

                val cv = ContentValues().apply {
                    put(MediaStore.MediaColumns.DISPLAY_NAME, dispName)
                    put(MediaStore.MediaColumns.MIME_TYPE, mime)
                    put(MediaStore.MediaColumns.RELATIVE_PATH, relPath)
                    put(MediaStore.MediaColumns.IS_PENDING, 1)
                    if (taken > 0) put(MediaStore.MediaColumns.DATE_TAKEN, taken)
                }
                val outUri = contentResolver.insert(col, cv) ?: throw IllegalStateException("insert 실패")
                try {
                    contentResolver.openOutputStream(outUri)!!.use { out ->
                        contentResolver.openInputStream(srcUri)!!.use { inp -> inp.copyTo(out, 262144) }
                    }
                    cv.clear(); cv.put(MediaStore.MediaColumns.IS_PENDING, 0)
                    contentResolver.update(outUri, cv, null, null)
                    okN++
                } catch (e: Exception) {
                    try { contentResolver.delete(outUri, null, null) } catch (_: Exception) {}
                    throw e
                }
            } catch (_: Exception) { failN++ }
            prog(id, i + 1, refs.length())
        }
        return JSONObject().put("ok", okN).put("skip", skipN).put("fail", failN).put("album", name)
    }

    /* ---------- 정리함 → 휴지통 (시스템 확인창 1번, 30일 뒤 자동 삭제) ---------- */

    private fun doTrash(id: String, p: JSONObject) {
        try {
            if (trashPending != null) {
                // 시스템 확인창이 이미 떠 있음 — 중복 요청은 취소로 응답
                done(id, true, JSONObject().put("done", false).put("count", 0))
                return
            }
            val refs = p.optJSONArray("refs") ?: JSONArray()
            val uris = ArrayList<Uri>()
            for (i in 0 until refs.length()) {
                val (mt, mid) = parseRef(refs.getString(i))
                uris.add(uriFor(mt, mid))
            }
            if (uris.isEmpty()) { done(id, true, JSONObject().put("done", false).put("count", 0)); return }
            val pi = MediaStore.createTrashRequest(contentResolver, uris, true)
            trashPending = { ok -> done(id, true, JSONObject().put("done", ok).put("count", uris.size)) }
            trashLauncher.launch(IntentSenderRequest.Builder(pi.intentSender).build())
        } catch (e: Exception) { fail(id, e) }
    }

    /* ---------- 동영상 등 원본을 다른 앱(갤러리·플레이어)으로 열기 ---------- */

    private fun doOpen(id: String, p: JSONObject) {
        try {
            val (mt, mid) = parseRef(p.optString("ref"))
            val uri = uriFor(mt, mid)
            val it = Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, contentResolver.getType(uri) ?: if (mt == "v") "video/*" else "image/*")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            startActivity(it)
            done(id, true, JSONObject().put("ok", true))
        } catch (e: Exception) { fail(id, e) }
    }

    /* ---------- 텍스트 파일 저장 (백업 JSON → 다운로드 폴더) ---------- */

    private fun doSaveText(p: JSONObject): JSONObject {
        val filename = p.optString("filename").ifEmpty { "저장.txt" }
        val text = p.optString("text")
        val mime = if (filename.endsWith(".json")) "application/json" else "text/plain"
        val cv = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, filename)
            put(MediaStore.MediaColumns.MIME_TYPE, mime)
            put(MediaStore.MediaColumns.RELATIVE_PATH, "Download/")
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val col = MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        val outUri = contentResolver.insert(col, cv) ?: throw IllegalStateException("저장 실패")
        contentResolver.openOutputStream(outUri)!!.use { it.write(text.toByteArray(Charsets.UTF_8)) }
        cv.clear(); cv.put(MediaStore.MediaColumns.IS_PENDING, 0)
        contentResolver.update(outUri, cv, null, null)
        return JSONObject().put("ok", true).put("where", "다운로드(Download) 폴더")
    }

    /* ---------- 썸네일·원본 스트리밍 (WebView 경로 핸들러) ---------- */

    private fun notFound() = WebResourceResponse(
        "text/plain", "utf-8", 404, "Not Found", mapOf(), ByteArrayInputStream(ByteArray(0))
    )

    inner class ThumbHandler : WebViewAssetLoader.PathHandler {
        override fun handle(path: String): WebResourceResponse {
            return try {
                val cached = thumbCache.get(path)
                val bytes = cached ?: run {
                    val seg = path.split("/")
                    val bmp = contentResolver.loadThumbnail(uriFor(seg[0], seg[1].toLong()), Size(480, 480), null)
                    val bo = ByteArrayOutputStream()
                    bmp.compress(Bitmap.CompressFormat.JPEG, 82, bo)
                    bmp.recycle()
                    bo.toByteArray().also { thumbCache.put(path, it) }
                }
                WebResourceResponse("image/jpeg", null, ByteArrayInputStream(bytes)).apply {
                    responseHeaders = mapOf("Cache-Control" to "max-age=86400")
                }
            } catch (_: Exception) { notFound() }
        }
    }

    inner class MediaHandler : WebViewAssetLoader.PathHandler {
        override fun handle(path: String): WebResourceResponse {
            return try {
                val seg = path.split("/")
                val uri = uriFor(seg[0], seg[1].toLong())
                val mime = contentResolver.getType(uri) ?: if (seg[0] == "v") "video/mp4" else "image/jpeg"
                WebResourceResponse(mime, null, contentResolver.openInputStream(uri))
            } catch (_: Exception) { notFound() }
        }
    }
}
