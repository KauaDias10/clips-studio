import { useEffect, useRef, useState } from 'react'
import { API_BASE, api } from '../lib/api'
import type { Clip, LiveOverlay, TranslationPreview, WatermarkConfig } from '../lib/types'
import { Scissors, YouTube } from './icons'
import LiveTextOverlay from './LiveTextOverlay'
import TimelineEditor from './TimelineEditor'
import { DEFAULT_CAPTION_STYLE } from './CaptionStyleControls'
import { youtubeEnabledSync } from '../lib/youtube'
import { t } from '../lib/i18n'

/** Live, draggable watermark preview over the editor video. Shows the
 *  text/logo where it will burn in, updates as the controls change, and
 *  drag repositions it (switching to a 'custom' point) so a static
 *  watermark can be placed off anything important. */
function WatermarkOverlay({
  config,
  onChange
}: {
  config: WatermarkConfig
  onChange: (patch: Partial<WatermarkConfig>) => void
}): JSX.Element {
  const boxRef = useRef<HTMLDivElement>(null)
  const [box, setBox] = useState({ w: 0, h: 0 })
  const dragging = useRef(false)

  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const pos = config.position ?? 'bottom_right'
  const pad = (config.padding ?? 0.04) * 100
  const opacity = config.opacity ?? 0.85
  const moving = pos === 'moving'

  const place = (p: string): React.CSSProperties => {
    const s: React.CSSProperties = { position: 'absolute' }
    if (p === 'custom') {
      s.left = `${(config.x ?? 0.5) * 100}%`
      s.top = `${(config.y ?? 0.5) * 100}%`
      s.transform = 'translate(-50%, -50%)'
      return s
    }
    if (p.includes('top')) s.top = `${pad}%`
    if (p.includes('bottom')) s.bottom = `${pad}%`
    if (p.includes('left')) s.left = `${pad}%`
    if (p.includes('right')) s.right = `${pad}%`
    if (p === 'center') {
      s.top = '50%'
      s.left = '50%'
      s.transform = 'translate(-50%, -50%)'
    }
    return s
  }

  const Mark = ({ ghost }: { ghost?: boolean }): JSX.Element => {
    const showImg = (config.type === 'image' || config.type === 'both') && config.image_asset
    const showTxt = (config.type === 'text' || config.type === 'both') && config.text
    return (
      <div
        className="flex flex-col items-center gap-0.5 leading-none pointer-events-none"
        style={{ opacity: ghost ? opacity * 0.4 : opacity }}
      >
        {showImg && (
          <img
            src={api.brandingAssetUrl(config.image_asset!)}
            alt=""
            style={{ width: `${(config.scale ?? 0.18) * box.w}px` }}
            className="max-w-none"
            draggable={false}
          />
        )}
        {showTxt && (
          <span
            style={{
              color: config.color ?? '#FFFFFF',
              fontFamily: config.font,
              fontSize: `${Math.max(8, (config.font_size ?? 42) * (box.h / 1920))}px`,
              textShadow: config.shadow ? '0 1px 3px rgba(0,0,0,0.9)' : 'none',
              transform: config.rotation ? `rotate(${config.rotation}deg)` : undefined,
              fontWeight: 700,
              whiteSpace: 'nowrap'
            }}
          >
            {config.text}
          </span>
        )}
      </div>
    )
  }

  const startDrag = (e: React.PointerEvent): void => {
    if (moving) return
    dragging.current = true
    ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
  }
  const onMove = (e: React.PointerEvent): void => {
    if (!dragging.current) return
    const r = boxRef.current?.getBoundingClientRect()
    if (!r) return
    const x = Math.max(0.02, Math.min(0.98, (e.clientX - r.left) / r.width))
    const y = Math.max(0.02, Math.min(0.98, (e.clientY - r.top) / r.height))
    onChange({ position: 'custom', x: Number(x.toFixed(3)), y: Number(y.toFixed(3)) })
  }

  return (
    <div ref={boxRef} className="absolute inset-0 z-10 pointer-events-none">
      {moving ? (
        // Two faint ghosts at the side edge-centres show the L/R travel.
        <>
          <div style={{ position: 'absolute', top: '50%', left: `${pad}%`, transform: 'translateY(-50%)' }}>
            <Mark ghost />
          </div>
          <div style={{ position: 'absolute', top: '50%', right: `${pad}%`, transform: 'translateY(-50%)' }}>
            <Mark ghost />
          </div>
          <span className="absolute bottom-14 left-1/2 -translate-x-1/2 text-[10px] text-white/80 bg-black/40 px-1.5 py-0.5 rounded">
            moves left ↔ right
          </span>
        </>
      ) : (
        <div
          style={place(pos)}
          className="pointer-events-auto cursor-move touch-none ring-1 ring-white/0 hover:ring-white/40 rounded"
          onPointerDown={startDrag}
          onPointerMove={onMove}
          onPointerUp={() => (dragging.current = false)}
          title={t('Drag to reposition')}
        >
          <Mark />
        </div>
      )}
    </div>
  )
}

/** Input types that are controls, not somewhere text is typed. */
const NOT_TYPING = new Set(['range', 'checkbox', 'radio', 'color', 'button', 'submit', 'reset', 'file'])

/** An Apply being re-rendered, as the editor shows it. */
export interface ApplyState {
  jobId: number
  phase: 'queued' | 'running' | 'done' | 'failed'
  started: number
  ended?: number
  error?: string
}

function elapsed(from: number, to?: number): string {
  const s = Math.max(0, Math.round(((to ?? Date.now()) - from) / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** Full-page editing workspace. */
export default function EditorView({
  clip,
  onClose,
  onChanged
}: {
  clip: Clip
  onClose: () => void
  onChanged: () => void
}): JSX.Element {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [previewSrc, setPreviewSrc] = useState<string | null>(null)
  const [watermark, setWatermark] = useState<WatermarkConfig | null>(clip.render_opts?.watermark ?? null)
  const [liveOverlay, setLiveOverlay] = useState<LiveOverlay | null>(null)
  const isLandscape = !!clip.render_opts?.profile

  const [translated, setTranslated] = useState<TranslationPreview | null>(null)

  // Apply's re-render, followed until it is done. Kept here, not in the
  // TimelineEditor: the clip comes back under a new id when it finishes, and
  // the timeline starts afresh on it — the outcome must outlive that.
  const [applying, setApplying] = useState<ApplyState | null>(null)
  useEffect(() => {
    if (!applying || applying.phase === 'done' || applying.phase === 'failed') return
    let alive = true
    const id = setInterval(async () => {
      try {
        const job = await api.job(applying.jobId)
        if (!alive) return
        if (job.status === 'done') {
          setApplying((a) => (a ? { ...a, phase: 'done', ended: Date.now() } : a))
          onChanged() // the new file and row: the editor moves onto them
        } else if (job.status === 'failed' || job.status === 'cancelled') {
          setApplying((a) => (a ? { ...a, phase: 'failed', error: job.error || job.status } : a))
        } else {
          setApplying((a) => (a ? { ...a, phase: job.status === 'running' ? 'running' : 'queued' } : a))
        }
      } catch {
        // A missed poll is not a verdict; the next one asks again.
      }
    }, 1200)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [applying?.jobId, applying?.phase])
  // The ticking clock on the banner.
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!applying || applying.phase === 'done' || applying.phase === 'failed') return
    const id = setInterval(() => setTick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [applying?.phase])
  // A success note goes away on its own.
  useEffect(() => {
    if (applying?.phase !== 'done') return
    const id = setTimeout(() => setApplying(null), 6000)
    return () => clearTimeout(id)
  }, [applying?.phase])

  useEffect(() => {
    setPreviewSrc(null)
    setWatermark(clip.render_opts?.watermark ?? null)
    setLiveOverlay(null)
    setTranslated(null)
  }, [clip.id])

  /** What LiveTextOverlay draws. A translated language being previewed wins
   *  over the pending-edit overlay: it is what the creator asked to look at,
   *  and it reuses the same masking so the English already burned into the
   *  clip file is blurred out underneath instead of ghosting through. */
  const captionStyle = { ...DEFAULT_CAPTION_STYLE, ...clip.render_opts?.caption_style }
  const overlay: LiveOverlay | null = translated
    ? {
        hook: null,
        captions: {
          lines: translated.lines,
          // The subtitle's own style, except that a non-Latin script forces
          // a font that has the glyphs — exactly what the burn does.
          style: { ...translated.style, font: translated.font ?? translated.style.font }
        },
        bakedKeep: liveOverlay?.bakedKeep,
        keep: liveOverlay?.keep ?? [],
        burned:
          (clip.render_opts?.captions ?? clip.render_opts?.job_captions ?? true) !== false &&
          translated.source.length > 0
            ? { lines: translated.source, style: captionStyle }
            : null,
        burnedHook: null
      }
    : liveOverlay

  // The header's YouTube button just asks the timeline editor to open its
  // YouTube tab. activeTab lives down there, and lifting it up here for one
  // button would be a lot of plumbing for a shortcut.
  const [tabRequest, setTabRequest] = useState<{ tab: 'youtube'; n: number } | null>(null)
  const [ytEnabled, setYtEnabled] = useState(youtubeEnabledSync())
  useEffect(() => {
    let alive = true
    api
      .youtubeStatus()
      .then((s) => alive && setYtEnabled(Boolean(s.enabled)))
      .catch(() => {
        /* leave the mirror's answer alone */
      })
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      // Not while typing: Escape in a text field gives up what is being
      // typed there, never the whole editor and every edit made in it. Only
      // fields that take text count: a slider or a checkbox keeps focus once
      // clicked, and Escape from there still leaves the editor as it always did.
      const t = e.target as HTMLElement | null
      const typing =
        !!t &&
        (t.tagName === 'TEXTAREA' ||
          t.isContentEditable ||
          (t instanceof HTMLInputElement && !NOT_TYPING.has(t.type)))
      if (e.key === 'Escape' && !typing) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <button
          onClick={onClose}
          className="px-3 py-1.5 rounded-lg bg-raised text-sm hover:bg-raised/70"
        >
          ← Back to clips
        </button>
        <p className="font-semibold truncate inline-flex items-center gap-2">
          <Scissors size={15} /> Editing — {clip.title || clip.hook || 'Untitled clip'}
        </p>
        {/* Nothing at all when publishing is switched off in Settings. */}
        {ytEnabled && (
          <button
            onClick={() => setTabRequest({ tab: 'youtube', n: (tabRequest?.n ?? 0) + 1 })}
            className="ml-auto shrink-0 px-3 py-1.5 rounded-lg bg-raised text-sm hover:bg-raised/70 inline-flex items-center gap-1.5"
            title={t("Publish this clip to YouTube")}
          >
            <YouTube size={15} /> YouTube
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5 items-start">
        <div className="lg:col-span-2 sticky top-6 space-y-2">
          <div
            className={`relative mx-auto max-w-full ${
              isLandscape ? 'w-full aspect-video' : 'h-[74vh] aspect-[9/16]'
            }`}
          >
            <video
              key={previewSrc ?? `clip-${clip.id}`}
              ref={videoRef}
              src={previewSrc ? `${API_BASE}${previewSrc}` : api.mediaUrl(clip.id)}
              controls
              autoPlay
              className="absolute inset-0 w-full h-full object-contain rounded-xl bg-base"
              aria-label={t('Editing preview')}
            />
            {/* Live watermark overlay — hidden while a baked draft is shown. */}
            {watermark && !previewSrc && (
              <WatermarkOverlay
                config={watermark}
                onChange={(patch) => setWatermark({ ...watermark, ...patch })}
              />
            )}
            {/* Pending hook / caption text — or a translated language being
                auditioned — drawn live over the video. */}
            {!previewSrc && <LiveTextOverlay videoRef={videoRef} overlay={overlay} />}
            {translated && !previewSrc && (
              <span className="absolute bottom-2 left-2 z-20 bg-black/70 text-white/85 text-[10px] px-2 py-0.5 rounded">
                {translated.language.toUpperCase()} preview — this is how the burn will look
              </span>
            )}
            {previewSrc && !applying && (
              <span className="absolute top-2 left-2 z-20 bg-accent/90 text-black text-[10px] font-bold px-2 py-0.5 rounded">
                PREVIEW — all edits applied (not saved until Apply)
              </span>
            )}
            {applying && (
              <div
                role="status"
                className={`absolute inset-x-2 top-2 z-30 rounded-lg px-3 py-2 text-xs font-medium shadow-lg flex items-center gap-2 ${
                  applying.phase === 'done'
                    ? 'bg-emerald-500/95 text-black'
                    : applying.phase === 'failed'
                      ? 'bg-red-500/95 text-white'
                      : 'bg-black/80 text-white'
                }`}
              >
                {(applying.phase === 'queued' || applying.phase === 'running') && (
                  <span className="size-3 rounded-full border-2 border-white/40 border-t-white animate-spin shrink-0" />
                )}
                <span className="flex-1">
                  {applying.phase === 'queued' &&
                    `${t('Edits saved — waiting for the video being processed to finish')} (${elapsed(applying.started)})`}
                  {applying.phase === 'running' && `${t('Applying your edits…')} (${elapsed(applying.started)})`}
                  {applying.phase === 'done' &&
                    `✓ ${t('Edits applied — this is the new clip')} (${elapsed(applying.started, applying.ended)})`}
                  {applying.phase === 'failed' && `${t('Applying failed')}: ${applying.error ?? ''}`}
                </span>
                {(applying.phase === 'done' || applying.phase === 'failed') && (
                  <button type="button" className="opacity-80 hover:opacity-100" onClick={() => setApplying(null)}>
                    ✕
                  </button>
                )}
              </div>
            )}
          </div>
          {isLandscape && (
            <p className="text-center text-xs text-muted">Longform clip — 1920×1080 horizontal</p>
          )}
        </div>
        <div className="lg:col-span-3 min-w-0 space-y-4">
          <TimelineEditor
            clip={clip}
            videoRef={videoRef}
            onChanged={onChanged}
            applying={applying !== null && (applying.phase === 'queued' || applying.phase === 'running')}
            onApplyStarted={(jobId) => setApplying({ jobId, phase: 'queued', started: Date.now() })}
            onPreview={setPreviewSrc}
            onLiveOverlay={setLiveOverlay}
            onTranslationPreview={setTranslated}
            watermark={watermark}
            setWatermark={setWatermark}
            tabRequest={tabRequest ?? undefined}
          />
        </div>
      </div>
    </div>
  )
}
