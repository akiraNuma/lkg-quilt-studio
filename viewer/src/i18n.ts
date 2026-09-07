// The authority for on-screen text. Writing conventions are in `.claude/rules/viewer-vue.md`.

import { ref, watchEffect } from 'vue'

export const LOCALES = ['ja', 'en'] as const
export type Locale = (typeof LOCALES)[number]

export const LOCALE_LABEL: Record<Locale, string> = {
  ja: '日本語',
  en: 'English',
}

const ja = {
  'app.tagline': 'ステレオ動画を Looking Glass の quilt 動画にする',
  'app.retry': 'もう一度',

  'display.title': 'ディスプレイ',
  'display.state.idle': '未接続',
  'display.state.connecting': '接続中',
  'display.state.connected': '接続済み',
  'display.state.unavailable': '接続できない',
  'display.connect': 'Bridge に接続',
  'display.refresh': '再検出',
  'display.disconnect': '切断',
  'display.hint':
    '接続すると機種が自動で入る。実機に出すには接続が要る',

  'source.title': '素材',
  'source.pick': '動画を選ぶ',
  'source.dropHint': 'または、ここに動画をドラッグ＆ドロップ',
  'source.oneFile': '動画は1つずつ取り込んでください。',
  'source.uploading': '取り込み中…',
  'source.meta': '{width}x{height} / {frames} フレーム / {fps} fps',
  'source.layout': '並び',
  'source.display': '機種',
  'source.projection': '写り方',
  'source.fit': '収め方',
  'source.choose': '選ぶ',
  'source.swapEyes': '左右を入れ替える',
  'source.warn.preset':
    '機種のプリセットが見つからない。一覧から選び直す',
  'source.warn.unknownLayout':
    '並びを判定できなかった。絵が真っ二つに切れていたら別の並びにする',
  'source.warn.layout':
    '{layout} に見える。違うと絵が真っ二つに切れる',
  'source.warn.fisheye':
    '魚眼（VR180）に見える。平面で読むと黒い縁が入り、視差も合わない',
  'source.warn.detected':
    '接続中は {display}。このままだと別機種向けの quilt になる',

  'tune.title': '調整',
  'tune.view': '視点',
  'tune.convergence': '収束面',
  'tune.convergenceHint':
    '収束面は画面と同じ奥行きに見える面。＋で手前へ、−で奥へ動く',
  'tune.baked':
    '書き出しに入る収束面 {total} px（自動 {base} ＋ 手動 {shift}）',
  'tune.deviceHint': '実機に映したまま、下の値を動かして詰められる',
  'tune.redraw': 'ここから下は動かすと描き直す',
  'tune.span': '立体の強さ',
  'tune.fov': '視野角',
  'tune.frame': 'フレーム',
  'tune.spanNote': '立体を強くしすぎると端の穴埋めが増えて荒れる',
  'tune.range': '{min} 〜 {max} の数で入れる',

  'export.title': '書き出し',
  'export.start': '開始',
  'export.frames': 'フレーム数',
  'export.toEnd': '最後まで',
  'export.copyAudio': '音声を残す',
  'export.badNumber':
    '数として読めない（全角で入っていないか確認する）',
  'export.plan': '{start} 〜 {last} の {count} フレーム',
  'export.submit': '書き出す',
  'export.cancel': '中止',
  'export.close': '閉じる',
  'export.play': '再生する',
  'export.download': 'ダウンロード',
  'export.remaining': '残り およそ {time}',
  'export.progress': '{done} / {total} フレーム',
  'export.doneFrames': '{status}（{frames} フレーム）',

  'job.queued': '順番待ち',
  'job.running': '変換中',
  'job.done': '完了',
  'job.failed': '失敗した',
  'job.cancelled': '中止した',

  'stage.empty': '素材を選ぶと 1 枚目がここに出る',
  'stage.frameName': '{name} の {frame} フレーム目',
  'stage.rendering': '描き直している…',
  'stage.mode.lenticular': 'レンチキュラー',
  'stage.mode.single': '1 視点',
  'stage.mode.quilt': 'quilt',
  'stage.moveOut': 'Looking Glass へ移す',
  'stage.bringBack': 'こちらへ戻す',
  'stage.needBridge': 'Bridge に接続すると移せる',
  'stage.stripes': 'ふつうのモニタでは縞に見えるのが正しい',
  'stage.play': '再生',
  'stage.pause': '一時停止',
  'stage.volume': '音量',
  'stage.mute': 'ミュート',
  'stage.unmute': 'ミュート解除',
  'stage.seek': '再生位置',
  'stage.moved':
    '別窓へ移した。その窓を Looking Glass 側へ動かして、窓の中をダブルクリックで全画面にする',
  'stage.popupBlocked':
    '別窓を開けなかった。ポップアップの許可を確認する',
  'stage.sizeNote':
    '描画バッファ {actual} が機種の {expected} と違う。窓を Looking Glass 側で全画面にする',
  'stage.noWebgl': 'WebGL2 が使えないブラウザでは表示できない',

  'library.title': 'ライブラリ',
  'library.outputs': '書き出した quilt 動画',
  'library.sources': '取り込んだ素材',
  'library.empty': 'まだありません',
  'library.refresh': '一覧を更新',
  'library.play': '再生',
  'library.download': 'ダウンロード',
  'library.use': '使う',
  'library.inUse': '調整中',
  'library.delete': '消す',
  'library.confirm': '消す？',
  'library.yes': 'はい',
  'library.no': 'やめる',
  'library.total': '{count} 件 / {size}',
  'library.leftovers': '失敗・中止したジョブ',
  'library.open': 'ファイルや URL から開く',
  'library.pickFile': 'ファイルを選ぶ',
  'library.load': '読み込む',
  'library.uri': 'http(s) の URL かファイルパス',

  'quilt.naming':
    'ファイル名が quilt の規約（例: sample_qs5x9a1.777.mp4）になっていない。converter が付ける名前のまま渡す',
  'quilt.mismatchTiles':
    'タイル数が違う（動画 {video} / 機種 {display}）',
  'quilt.mismatchAspect':
    'タイルの縦横比が違う（動画 {video} / 機種 {display}）',

  'lenticular.badCalibration':
    'キャリブレーション値が不正（{values}）',
  'lenticular.tooSmall':
    'quilt の解像度がタイル数より小さい（quilt {size} / タイル {tiles}）',

  'bridge.unavailable':
    'Bridge に接続できない。Looking Glass Bridge を起動して再試行する',
  'bridge.loadFailed': 'Bridge の読み込みに失敗した: {error}',
  'bridge.notFound': 'Looking Glass が見つからない',
  'bridge.unknownSerial': '(不明)',

  'api.unreachable':
    '変換 API に届かなかった。api が起動しているか確認する',
  'api.status': '変換 API が {status} を返した',

  'unit.seconds': '{value} 秒',
  'unit.minutes': '{value} 分',
  'unit.hours': '{value} 時間',
} as const

export type MessageKey = keyof typeof ja

const en: Record<MessageKey, string> = {
  'app.tagline': 'Turn stereo video into Looking Glass quilt video',
  'app.retry': 'Try again',

  'display.title': 'Display',
  'display.state.idle': 'Not connected',
  'display.state.connecting': 'Connecting',
  'display.state.connected': 'Connected',
  'display.state.unavailable': 'Unavailable',
  'display.connect': 'Connect to Bridge',
  'display.refresh': 'Rescan',
  'display.disconnect': 'Disconnect',
  'display.hint':
    'Connecting fills in the model. It is only needed to show on the device.',

  'source.title': 'Source',
  'source.pick': 'Choose a video',
  'source.dropHint': 'Or drag and drop a video here',
  'source.oneFile': 'Please import one video at a time.',
  'source.uploading': 'Importing…',
  'source.meta': '{width}x{height} / {frames} frames / {fps} fps',
  'source.layout': 'Layout',
  'source.display': 'Model',
  'source.projection': 'Projection',
  'source.fit': 'Fit',
  'source.choose': 'Choose',
  'source.swapEyes': 'Swap left and right',
  'source.warn.preset':
    'That model preset is gone. Pick one from the list.',
  'source.warn.unknownLayout':
    'Could not tell the layout. If the picture is cut in half, pick another one.',
  'source.warn.layout':
    'This looks like {layout}. A wrong layout cuts the picture in half.',
  'source.warn.fisheye':
    'This looks like fisheye (VR180). Read as flat it keeps a black rim and the disparity is off.',
  'source.warn.detected':
    'The connected device is {display}. As is, the quilt is built for another model.',

  'tune.title': 'Tune',
  'tune.view': 'View',
  'tune.convergence': 'Convergence',
  'tune.convergenceHint':
    'The convergence plane sits at screen depth. + pulls the subject forward, − pushes it back.',
  'tune.baked':
    'Convergence written into the export: {total} px (auto {base} + manual {shift})',
  'tune.deviceHint':
    'Keep it on the device while you tune the values below.',
  'tune.redraw': 'Changing anything below redraws the frame',
  'tune.span': 'Depth strength',
  'tune.fov': 'Field of view',
  'tune.frame': 'Frame',
  'tune.spanNote':
    'Too much depth leaves more holes to fill at the edge views, and they look rough',
  'tune.range': 'Enter a number between {min} and {max}',

  'export.title': 'Export',
  'export.start': 'Start',
  'export.frames': 'Frames',
  'export.toEnd': 'to the end',
  'export.copyAudio': 'Keep the audio',
  'export.badNumber': 'Not a number (check for full-width digits)',
  'export.plan': '{count} frames, {start} to {last}',
  'export.submit': 'Export',
  'export.cancel': 'Cancel',
  'export.close': 'Close',
  'export.play': 'Play it',
  'export.download': 'Download',
  'export.remaining': 'about {time} left',
  'export.progress': '{done} / {total} frames',
  'export.doneFrames': '{status} ({frames} frames)',

  'job.queued': 'Queued',
  'job.running': 'Converting',
  'job.done': 'Done',
  'job.failed': 'Failed',
  'job.cancelled': 'Cancelled',

  'stage.empty': 'Pick a source and the first frame shows up here',
  'stage.frameName': '{name}, frame {frame}',
  'stage.rendering': 'Redrawing…',
  'stage.mode.lenticular': 'Lenticular',
  'stage.mode.single': 'Single view',
  'stage.mode.quilt': 'Quilt',
  'stage.moveOut': 'Move to Looking Glass',
  'stage.bringBack': 'Bring it back',
  'stage.needBridge': 'Connect to Bridge to move it',
  'stage.stripes': 'On a normal monitor the stripes are correct',
  'stage.play': 'Play',
  'stage.pause': 'Pause',
  'stage.volume': 'Volume',
  'stage.mute': 'Mute',
  'stage.unmute': 'Unmute',
  'stage.seek': 'Playback position',
  'stage.moved':
    'Moved to a separate window. Drag it onto the Looking Glass, then double-click inside it for full screen.',
  'stage.popupBlocked':
    'Could not open the window. Check the popup permission.',
  'stage.sizeNote':
    'The drawing buffer {actual} differs from the device {expected}. Make the window full screen on the Looking Glass.',
  'stage.noWebgl':
    'This browser has no WebGL2, so nothing can be drawn',

  'library.title': 'Library',
  'library.outputs': 'Exported quilt videos',
  'library.sources': 'Uploaded sources',
  'library.empty': 'Nothing here yet',
  'library.refresh': 'Refresh',
  'library.play': 'Play',
  'library.download': 'Download',
  'library.use': 'Use',
  'library.inUse': 'Tuning',
  'library.delete': 'Delete',
  'library.confirm': 'Delete it?',
  'library.yes': 'Yes',
  'library.no': 'Keep it',
  'library.total': '{count} items / {size}',
  'library.leftovers': 'Failed or cancelled jobs',
  'library.open': 'Open a file or a URL',
  'library.pickFile': 'Choose a file',
  'library.load': 'Load',
  'library.uri': 'An http(s) URL or a file path',

  'quilt.naming':
    'The file name does not follow the quilt convention (e.g. sample_qs5x9a1.777.mp4). Keep the name the converter gives it.',
  'quilt.mismatchTiles':
    'Tile counts differ (video {video} / device {display})',
  'quilt.mismatchAspect':
    'Tile aspect ratios differ (video {video} / device {display})',

  'lenticular.badCalibration':
    'Invalid calibration values ({values})',
  'lenticular.tooSmall':
    'The quilt resolution is smaller than the tile count (quilt {size} / tiles {tiles})',

  'bridge.unavailable':
    'Cannot reach Bridge. Start Looking Glass Bridge and try again.',
  'bridge.loadFailed': 'Failed to load Bridge: {error}',
  'bridge.notFound': 'No Looking Glass found',
  'bridge.unknownSerial': '(unknown)',

  'api.unreachable':
    'Could not reach the converter API. Check that it is running.',
  'api.status': 'The converter API returned {status}',

  'unit.seconds': '{value} s',
  'unit.minutes': '{value} min',
  'unit.hours': '{value} h',
}

const messages: Record<Locale, Record<MessageKey, string>> = {
  ja,
  en,
}

const STORAGE_KEY = 'lkg-quilt-studio.locale'

export const locale = ref<Locale>(initial())

export function setLocale(next: Locale): void {
  locale.value = next
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch {
    // A private window cannot write; the switch itself still works, so move on silently
  }
}

/** Look up a message. `{name}` is filled from `params`. */
export function t(
  key: MessageKey,
  params?: Record<string, string | number>
): string {
  const text = messages[locale.value][key]
  if (params === undefined) return text
  return text.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole
  )
}

/** Saved choice, then the browser language, then Japanese. */
function initial(): Locale {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (isLocale(saved)) return saved
  } catch {
    // localStorage is merely absent (tests, restricted modes), so fall through to the next source
  }
  const preferred =
    typeof navigator === 'undefined' ? undefined : navigator.language
  return preferred !== undefined && !preferred.startsWith('ja')
    ? 'en'
    : 'ja'
}

function isLocale(value: string | null): value is Locale {
  return LOCALES.includes(value as Locale)
}

// Keep <html lang> in step: font selection and screen readers read it
if (typeof document !== 'undefined') {
  watchEffect(() => (document.documentElement.lang = locale.value))
}
