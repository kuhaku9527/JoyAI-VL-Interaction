'use strict';

// i18n_device_label.js
// Runtime localization, extracted from index.html so the monolith shrinks AND
// the mapping becomes unit-testable (tests/i18n_device_label.test.js,
// tests/i18n_ui_string.test.js).
//
// Public API (attached to window.JoyI18n for non-module usage):
//   localizeDeviceLabel(label) -> string
//   DEVICE_LABEL_MAP          -> Array<[RegExp, string]>
//   localizeUiString(text)    -> string   (issue #47: key-panel UI strings)
//   UI_STRING_MAP             -> Array<[RegExp, string]>
//   applyUiI18n(root?)        -> void      (runtime pass over static markup)
//
// Maps OS-reported English device names (e.g. "OBS Virtual Camera") and
// user-facing English UI strings (e.g. "Streaming", "Camera Selection") to
// Chinese. Conservative: only known English patterns are replaced; unknown
// labels — including already-Chinese strings on a zh-locale OS — pass through
// unchanged, so we never mistranslate. Loaded via <script src> in index.html
// <head> BEFORE the inline app script that calls window.JoyI18n.*.
//
// v1.0: extracted from the inline localizeDeviceLabel() cluster (PR #56).
// v1.1: added UI_STRING_MAP / localizeUiString / applyUiI18n for issue #47.

(function () {
  // Ordered most-specific first: a more specific phrase must precede its generic
  // substring so the generic rule does not partially mangle it
  // (e.g. "Integrated Webcam" before "Webcam"; "USB* Camera" before "Camera";
  // "FaceTime HD Camera" before "HD Camera" before "Camera"; "Headset Microphone"
  // before "Headset"/"Microphone").
  const DEVICE_LABEL_MAP = [
    [/\bOBS Virtual Camera\b/i, 'OBS 虚拟摄像头'],
    [/\bVirtual Camera\b/i, '虚拟摄像头'],
    [/\bIntegrated Webcam\b/i, '内置摄像头'],
    [/\bIntegrated Camera\b/i, '内置摄像头'],
    [/\bFaceTime HD Camera\b/i, 'FaceTime 高清摄像头'],
    [/\bHD Webcam\b/i, '高清摄像头'],
    [/\bUSB[\s0-9.]*Camera\b/i, 'USB 摄像头'],
    [/\bWebcam\b/i, '摄像头'],
    [/\bHD Camera\b/i, '高清摄像头'],
    [/\bCamera\b/i, '摄像头'],
    [/\bHeadset Microphone\b/i, '耳机麦克风'],
    [/\bHeadset\b/i, '耳机'],
    [/\bMicrophone\b/i, '麦克风'],
    [/\bMic\b/i, '麦克风'],
    [/\bSpeakers\b/i, '扬声器'],
    [/\bSpeaker\b/i, '扬声器'],
    [/\bBluetooth\b/i, '蓝牙'],
    [/\bHeadphones\b/i, '耳机'],
  ];

  function localizeDeviceLabel(label) {
    if (!label) return label;
    let s = label;
    for (const [re, zh] of DEVICE_LABEL_MAP) s = s.replace(re, zh);
    return s;
  }

  // --- UI string i18n (issue #47: key-panel localization) -------------------
  // Same discipline as DEVICE_LABEL_MAP: ordered most-specific first. A longer
  // phrase that contains a shorter key MUST precede it, otherwise the generic
  // rule mangles it mid-string. Examples enforced here:
  //   "RTSP Stream URL" before "RTSP Stream"
  //   "Camera Selection" / "VLM Output on Camera View" before "Camera"
  //   "Delete failed: " / "Save failed: " before "Delete " / ": "
  //   " chunks, " before ", "
  // Conservative passthrough: unknown strings, falsy input, and already-Chinese
  // strings are returned unchanged (never mistranslated).
  const UI_STRING_MAP = [
    [/\bStart webcam capture\b/i, '开始摄像头采集'],
    [/\bStop webcam capture\b/i, '停止摄像头采集'],
    [/\bStart RTSP capture\b/i, '开始 RTSP 采集'],
    [/\bStop RTSP capture\b/i, '停止 RTSP 采集'],
    [/\bStart screen capture\b/i, '开始屏幕采集'],
    [/\bStop screen capture\b/i, '停止屏幕采集'],
    [/\bRTSP Stream URL\b/i, 'RTSP 流地址'],
    [/\bRTSP Stream\b/i, 'RTSP 流'],
    [/\bVLM Output on Camera View\b/i, '摄像头画面 VLM 输出'],
    [/\bCamera Selection\b/i, '摄像头选择'],
    [/\bCamera\b/i, '摄像头'],
    [/No local VLM services found\. Using NVIDIA API Catalog \(requires API key from build\.nvidia\.com\)/i, '未找到本地 VLM 服务，改用 NVIDIA API Catalog（需 build.nvidia.com 的 API Key）'],
    [/Failed to load network settings: /i, '加载网络设置失败：'],
    [/Failed to load: /i, '加载失败：'],
    [/Delete failed: /i, '删除失败：'],
    [/Save failed: /i, '保存失败：'],
    [/Sync failed: /i, '同步失败：'],
    [/Ingest failed: /i, '导入失败：'],
    [/ chunks, /i, ' 个分块，'],
    [/\bSynced /i, '已同步 '],
    [/\bIngested /i, '已导入 '],
    [/\bDeleted /i, '已删除 '],
    [/\bSyncing /i, '正在同步 '],
    [/\bIngesting /i, '正在导入 '],
    [/\bDeleting /i, '正在删除 '],
    [/\bDelete /i, '删除 '],
    [/Saving\.\.\./i, '保存中...'],
    [/Saved\. Health re-tested below\./i, '已保存。下方已重新检测健康状态。'],
    [/Probing providers\.\.\./i, '正在探测提供方...'],
    [/Probe complete \(v1 traffic stays direct per ADR-0012 §4\)\./i, '探测完成（v1 流量按 ADR-0012 §4 直连）。'],
    [/Enter a wiki\/<game> folder path first\./i, '请先输入 wiki/<游戏> 文件夹路径。'],
    [/Provide both a namespace \(game\) and markdown text\./i, '请提供命名空间（游戏）与 markdown 文本。'],
    [/: /i, '：'],
    [/, /i, '，'],
    [/ embedded/i, ' 已嵌入'],
    [/ errors/i, ' 个错误'],
    [/ rows removed/i, ' 行已移除'],
    [/\bStreaming\b/i, '直播中'],
    [/Preparing first metrics\.\.\./i, '正在准备首批指标...'],
    [/\bModel configured\b/i, '模型已配置'],
    [/\bBT listening\b/i, '蓝牙监听中'],
    [/\bASR connection failed\b/i, 'ASR 连接失败'],
    [/\bConnected\b/i, '已连接'],
    [/\bDisconnected\b/i, '未连接'],
    [/\bNo cameras found\b/i, '未找到摄像头'],
    [/Error detecting cameras/i, '检测摄像头出错'],
    [/Detecting cameras\.\.\./i, '正在检测摄像头...'],
    [/\bLLM ERR\b/i, 'LLM 错误'],
    [/\bTTS ERR\b/i, 'TTS 错误'],
    [/\bKWS ERR\b/i, 'KWS 错误'],
    [/\bVideo Source\b/i, '视频源'],
    [/\bWebcam Capture\b/i, '摄像头采集'],
    [/\bScreen Capture\b/i, '屏幕采集'],
    [/\bIdle\b/i, '空闲'],
    [/\bProcessing Interval\b/i, '处理间隔'],
    [/\bFrames per Batch\b/i, '每批帧数'],
    [/\bServices\b/i, '服务'],
    [/\bAPI Base URL\b/i, 'API 基础地址'],
    [/\bAPI Key\b/i, 'API 密钥'],
    [/\bAPI URL\b/i, 'API 地址'],
    [/\bModel\b/i, '模型'],
    [/\bAPI Status\b/i, '接口状态'],
    [/\bMain LLM\b/i, '主 LLM'],
    [/\bSummarizer\b/i, '摘要'],
    [/\bSummary\b/i, '摘要'],
    [/\bEmbedding\b/i, '嵌入'],
    [/\bMemory Store\b/i, '记忆存储'],
    [/\bKnowledge Base\b/i, '知识库'],
    [/\bNo knowledge bases yet\./i, '暂无知识库'],
    [/\bGame \/ namespace\b/i, '游戏 / 命名空间'],
    [/Paste wiki markdown/i, '粘贴 wiki Markdown'],
    [/\bDrop first\b/i, '丢弃首段'],
    [/\bReady\b/i, '就绪'],
    [/\bLight\b/i, '浅色'],
    [/\bDark\b/i, '深色'],
    [/\bAuto\b/i, '自动'],
    [/\bPlain Text\b/i, '纯文本'],
    [/\bMid-term memory\b/i, '中期记忆'],
    [/\bLong-term memory\b/i, '长期记忆'],
    [/\bPilot \(listening\)/i, '驾驶员（监听中）'],
    [/Speaking:/i, '朗读：'],
    [/\bLayout\b/i, '布局'],
    [/\bVisual Effects\b/i, '视觉效果'],
    [/\bVisual Style\b/i, '视觉风格'],
    [/\bAudio Output\b/i, '音频输出'],
    [/\bBackground Model\b/i, '后台模型'],
    [/\bDebug\b/i, '调试'],
    [/\bNetwork Proxy\b/i, '网络代理'],
    [/\bMain Content Order\b/i, '主内容排序'],
    [/\bPop-in Animation\b/i, '弹入动画'],
    [/\bGreen Glow Effect\b/i, '绿色辉光'],
    [/\bFade Effect\b/i, '淡出效果'],
    [/\bColorful UI Accents\b/i, '彩色界面点缀'],
    [/\bSpeak VLM output\b/i, '朗读 VLM 输出'],
    [/\bEnable delegation solver\b/i, '启用量级委派求解'],
    [/\bFrame multiplier\b/i, '帧倍率'],
    [/\bMax background frames\b/i, '最大后台帧数'],
    [/\bShow request payload\b/i, '显示请求载荷'],
    [/\bShow response payload\b/i, '显示响应载荷'],
    [/\bShow memory state\b/i, '显示记忆状态'],
    [/\bEnable proxy\b/i, '启用代理'],
    [/\bProxy host\b/i, '代理主机'],
    [/\bProxy port\b/i, '代理端口'],
    [/\boptional\b/i, '可选'],
    [/\bChoose which element appears at the top\b/i, '选择置顶显示的元素'],
    [/\bShow text overlay directly on video feed\b/i, '在视频画面上直接叠加文字'],
    [/\bBorder glow on new VLM response\b/i, '新 VLM 回复时边框发光'],
    [/\bGradually fade response after 2 seconds\b/i, '2 秒后逐渐淡出回复'],
    [/\bColor-coded icons and input focus glows\b/i, '彩色图标与输入框聚焦发光'],
    [/\bPlay TTS audio for each visible response\b/i, '为每个可见回复播放 TTS 语音'],
    [/\bNone\b/i, '无'],
    [/\bAt the top\b/i, '顶部'],
    [/\bAt the bottom\b/i, '底部'],
    [/\bBT listening input device\b/i, '蓝牙监听输入设备'],
    [/Loading…/i, '加载中…'],
    [/ blocks · /i, ' 个数据块 · '],
    [/ indexed/i, ' 已索引'],
  ];

  function localizeUiString(text) {
    if (!text) return text;
    let s = text;
    for (const [re, zh] of UI_STRING_MAP) s = s.replace(re, zh);
    return s;
  }

  // Runtime localization pass for static markup.
  //   - Elements opt in with a `data-i18n` flag; their textContent is used as
  //     the lookup key (so the visible English stays the single source of truth
  //     and Chinese is resolved only from UI_STRING_MAP, never hardcoded here).
  //   - Attributes opt in with `data-i18n-title` / `data-i18n-aria` /
  //     `data-i18n-placeholder`; the attribute value is the lookup key.
  // Idempotent: a localized (Chinese) string never rematches an English key.
  function applyUiI18n(root) {
    root = root || (typeof document !== 'undefined' ? document : null);
    if (!root || typeof root.querySelectorAll !== 'function') return;
    root.querySelectorAll('[data-i18n]').forEach((el) => {
      const key = (el.textContent || '').trim();
      if (!key) return;
      const out = localizeUiString(key);
      if (out !== key) el.textContent = out;
    });
    const attrKeys = [
      ['data-i18n-title', 'title'],
      ['data-i18n-aria', 'aria-label'],
      ['data-i18n-placeholder', 'placeholder'],
    ];
    for (const [attr, prop] of attrKeys) {
      root.querySelectorAll('[' + attr + ']').forEach((el) => {
        const key = (el.getAttribute(attr) || '').trim();
        if (!key) return;
        const out = localizeUiString(key);
        if (out !== key) el.setAttribute(prop, out);
      });
    }
  }

  // window in browser/jsdom; globalThis fallback keeps a bare-node import safe.
  const root = typeof window !== 'undefined' ? window : globalThis;
  root.JoyI18n = {
    localizeDeviceLabel,
    DEVICE_LABEL_MAP,
    localizeUiString,
    UI_STRING_MAP,
    applyUiI18n,
  };
})();
