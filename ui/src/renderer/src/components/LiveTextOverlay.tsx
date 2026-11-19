import { useEffect, useRef, useState } from 'react'
import type { LiveOverlay } from '../lib/types'
import { bakedToOrig } from './TimelineEditor'
import BannerPreview from './BannerPreview'

/** Live DOM rendition of PENDING burned-in text — the hook title and
 *  restyled/corrected captions — drawn over the editor video in the same
 *  place and proportions the render will burn them (ASS styles are
 *  calibrated on a 1920-tall canvas; everything here scales by
 *  boxHeight/1920, which holds for portrait and landscape alike).
 *  Shown only while those changes are pending, so users see caption style,
 *  text fixes, censoring and hooks instantly instead of waiting for the
 *  ~1 minute Update-preview render. */
export default function LiveTextOverlay({
  videoRef,
  overlay
}: {
  videoRef: React.RefObject<HTMLVideoElement>
  overlay: LiveOverlay | null
}): JSX.Element | null {
  const boxRef = useRef<HTMLDivElement>(null)
  const [box, setBox] = useState({ w: 0, h: 0 })
  const [t, setT] = useState(0) // playhead in original-clip seconds
  const dragging = useRef(false)
  const [bannerDrag, setBannerDrag] = useState(false)

  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [overlay === null])

  // Follow playback on rAF (timeupdate is too coarse for 1-3 word captions).
  const bakedKeep = overlay?.bakedKeep
  useEffect(() => {
    if (!overlay) return
    let raf = 0
    const tick = (): void => {
      raf = requestAnimationFrame(tick)
      const el = videoRef.current
      if (!el) return
      const tOrig = bakedToOrig(el.currentTime, bakedKeep)
      setT((prev) => (Math.abs(prev - tOrig) > 0.02 ? tOrig : prev))
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [videoRef, bakedKeep, overlay === null])

  if (!overlay || (!overlay.hook && !overlay.captions && !overlay.banner)) return null

  const s = box.h / 1920 // ASS values are calibrated at a 1920-tall canvas

  // The hook burns at 0..seconds of the FINAL cut — convert the original-
  // timeline playhead to elapsed kept-time under the current edit.
  const elapsed = overlay.keep.reduce((acc, [a, b]) => acc + Math.max(0, Math.min(t, b) - a), 0)
  const showHook = overlay.hook && overlay.hook.text && elapsed <= overlay.hook.seconds

  const line = overlay.captions?.lines.find((l) => t >= l.start && t <= l.end)
  const st = overlay.captions?.style
  // The other speaker's line, in their colour (lib/speakerTurns.ts marks it).
  const lineColor = st && line?.speaker && st.second_speaker ? st.second_speaker_color : st?.color
  const capSize = st ? Math.max(40, Math.min(140, st.font_size)) * s : 0
  const capPos: React.CSSProperties =
    st?.position === 'custom'
      ? { bottom: `${100 - Math.max(8, Math.min(98, st.caption_y ?? 77))}%` }
      : st?.position === 'top'
      ? { top: 140 * s }
      : st?.position === 'middle'
        ? { top: '50%', transform: 'translateY(-50%)' }
        : { bottom: 440 * s }

  // Frosted strip over text that's ALREADY burned into the preview file, so
  // the old caption/hook doesn't ghost through behind the pending one.
  const burnedLine = overlay.burned?.lines.find((l) => t >= l.start && t <= l.end)
  const maskBand = (position: string, fontSizeAss: number, marginAss: number, text = ''): JSX.Element => {
    const size = Math.max(40, Math.min(140, fontSizeAss)) * s
    // As tall as the burned line really is (it wraps past ~16 letters at the
    // usual sizes), not a fixed three lines that stuck out as a blurred band.
    const rows = text.length > 16 * (90 / Math.max(40, Math.min(140, fontSizeAss))) ? 2 : 1
    const height = size * (rows * 1.3 + 0.5)
    const band: React.CSSProperties =
      position === 'custom'
        ? { bottom: `${100 - (overlay.burned?.style.caption_y ?? 77)}%`, height }
        : position === 'top'
        ? { top: Math.max(0, marginAss * s - size * 0.25), height }
        : position === 'middle'
          ? { top: '50%', transform: 'translateY(-50%)', height }
          : { bottom: Math.max(0, marginAss * s - size * 0.25), height }
    return (
      <div
        className="absolute inset-x-0"
        style={{
          ...band,
          margin: `0 ${30 * s}px`,
          borderRadius: 10 * s,
          backdropFilter: 'blur(16px)',
          background: 'rgba(0,0,0,0.35)'
        }}
      />
    )
  }

  // Dragging the caption up or down places it there (custom position).
  const moveTo = (e: React.PointerEvent): void => {
    const el = boxRef.current
    if (!el || !overlay.moveCaption) return
    const r = el.getBoundingClientRect()
    overlay.moveCaption(Math.round(Math.max(8, Math.min(98, ((e.clientY - r.top) / r.height) * 100))))
  }

  const outline = (px: number): React.CSSProperties => ({
    WebkitTextStroke: `${Math.max(1, px)}px black`,
    textShadow: `0 ${Math.max(1, 2 * s)}px ${Math.max(2, 5 * s)}px rgba(0,0,0,0.85)`
  })

  return (
    <div
      ref={boxRef}
      className="absolute inset-0 z-10 pointer-events-none overflow-hidden"
      style={{ containerType: 'size' }}
    >
      {/* The banner already burned into the file, frosted over, and the new one on top. */}
      {overlay.banner?.burned && (
        // Exactly the old banner's lines, not a fixed 3-line strip: a fixed
        // strip stuck out as a blurred band under a shorter title.
        <BannerPreview style={overlay.banner.burned} title={overlay.banner.title} mask />
      )}
      {overlay.banner?.show && (
        <BannerPreview
          style={overlay.banner.style}
          title={overlay.banner.title}
          dragging={bannerDrag}
          hint="Drag to move the title"
          handlers={
            overlay.moveBanner
              ? {
                  onPointerDown: (e) => {
                    e.currentTarget.setPointerCapture(e.pointerId)
                    setBannerDrag(true)
                  },
                  onPointerMove: (e) => {
                    const el = boxRef.current
                    if (!bannerDrag || !el || !overlay.moveBanner) return
                    const r = el.getBoundingClientRect()
                    overlay.moveBanner(
                      Math.round(Math.max(10, Math.min(90, ((e.clientX - r.left) / r.width) * 100))),
                      Math.round(Math.max(5, Math.min(95, ((e.clientY - r.top) / r.height) * 100)))
                    )
                  },
                  onPointerUp: () => setBannerDrag(false),
                  onPointerCancel: () => setBannerDrag(false)
                }
              : undefined
          }
        />
      )}
      {/* masks go first so pending text draws on top of them */}
      {burnedLine &&
        overlay.burned &&
        maskBand(
          overlay.burned.style.position,
          overlay.burned.style.font_size,
          overlay.burned.style.position === 'top' ? 140 : 440,
          burnedLine.text
        )}
      {overlay.burnedHook &&
        elapsed <= overlay.burnedHook.seconds &&
        maskBand('top', 96, 190, 'x'.repeat(40))}
      {showHook && overlay.hook && (
        <p
          className="absolute inset-x-0 text-center font-black leading-tight"
          style={{
            top: 190 * s,
            fontFamily: '"Arial Black", Arial, sans-serif',
            fontSize: `${96 * s}px`,
            color: '#FFFFFF',
            padding: `0 ${60 * s}px`,
            ...outline(4.5 * s)
          }}
        >
          {overlay.hook.text}
        </p>
      )}
      {line && st && (
        <p
          className={`absolute inset-x-0 text-center leading-snug select-none ${
            overlay.moveCaption ? 'pointer-events-auto cursor-grab active:cursor-grabbing' : ''
          }`}
          title={overlay.moveCaption ? 'Drag up or down to move the captions' : undefined}
          onPointerDown={(e) => {
            if (!overlay.moveCaption) return
            e.currentTarget.setPointerCapture(e.pointerId)
            dragging.current = true
          }}
          onPointerMove={(e) => dragging.current && moveTo(e)}
          onPointerUp={() => (dragging.current = false)}
          onPointerCancel={() => (dragging.current = false)}
          style={{
            touchAction: 'none',
            ...capPos,
            fontFamily: st.font,
            fontSize: `${capSize}px`,
            fontWeight: 700,
            color: lineColor,
            padding: `0 ${60 * s}px`,
            ...outline(3.5 * s)
          }}
        >
          {st.highlight ? (
            // Which word is being said right now. The burn uses Whisper's
            // real word timings; the preview has only the line's span, so it
            // splits it by word length — the same fallback the burn uses for
            // hand-edited text.
            (() => {
              const words = line.text.split(/\s+/).filter(Boolean)
              const weights = words.map((w) => Math.max(1, w.length))
              const total = weights.reduce((a, b) => a + b, 0)
              const span = Math.max(0.05, line.end - line.start)
              let acc = line.start
              const bounds = weights.map((wgt) => {
                const a = acc
                acc += (span * wgt) / total
                return a
              })
              let hot = -1
              bounds.forEach((b, i) => {
                if (t >= b) hot = i
              })
              return words.map((w, i) => (
                <span key={i} style={{ color: i === hot ? st.highlight_color : lineColor }}>
                  {(st.uppercase ? w.toUpperCase() : w) + (i < words.length - 1 ? ' ' : '')}
                </span>
              ))
            })()
          ) : st.uppercase ? (
            line.text.toUpperCase()
          ) : (
            line.text
          )}
        </p>
      )}
      {overlay.captions && (
        <span className="absolute top-2 right-2 bg-black/60 text-white/80 text-[10px] px-1.5 py-0.5 rounded">
          caption preview — Apply burns it in
        </span>
      )}
    </div>
  )
}
