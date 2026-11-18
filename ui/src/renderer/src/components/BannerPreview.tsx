import type React from 'react'
import type { CaptionStyle } from '../lib/types'

/** The title banner as video_editor/title_banner.py burns it, drawn in the
 *  DOM: the caption style example and the editor's live overlay both use it.
 *  Sizes are in container-height units (the parent sets containerType:
 *  'size'), from values calibrated on a 1920-tall frame, so it is the same
 *  size on the small example and over the video. */

// title_banner.py's numbers.
const SIZES: [number, number][] = [
  [78, 22],
  [66, 26],
  [58, 30]
]
const MAX_LINES = 3
const LINE = 1.18

const HASHTAG = /(^|\s)#[\p{L}\p{N}_]+/gu
const EMOJI = /[\u{1F000}-\u{1FFFF}☀-➿️‍]/gu

export function cleanTitle(title: string, uppercase: boolean): string {
  const text = (title || '')
    .replace(HASHTAG, ' ')
    .replace(EMOJI, '')
    .replace(/[\\{}]/g, '')
    .split(/\s+/)
    .filter(Boolean)
    .join(' ')
  return uppercase ? text.toUpperCase() : text
}

function wrap(words: string[], width: number): string[] {
  const lines: string[] = []
  for (const w of words) {
    if (lines.length && lines[lines.length - 1].length + 1 + w.length <= width) lines[lines.length - 1] += ' ' + w
    else lines.push(w)
  }
  return lines
}

function balanced(words: string[], width: number): string[] {
  const lines = wrap(words, width)
  const n = lines.length
  if (n < 2) return lines
  const total = words.join(' ').length
  for (let w = Math.max(1, Math.floor(total / n)); w <= width; w++) {
    const trial = wrap(words, w)
    if (trial.length === n) return trial
  }
  return lines
}

const clamp = (v: number | undefined, d: number, lo: number, hi: number): number =>
  typeof v === 'number' && Number.isFinite(v) ? Math.max(lo, Math.min(hi, v)) : d

/** How the title breaks into lines and how big it is, as the burn decides. */
export function bannerLayout(
  text: string,
  style: Required<CaptionStyle>
): { lines: string[]; size: number } {
  const words = text.split(' ').filter(Boolean)
  const grow = clamp(style.title_banner_size, 100, 50, 200) / 100
  let lines: string[] = []
  let size = SIZES[SIZES.length - 1][0]
  for (const [s, width] of SIZES) {
    size = s
    lines = balanced(words, Math.max(6, Math.floor(width / grow)))
    if (lines.length <= 2) break
  }
  if (lines.length > MAX_LINES) {
    lines = lines.slice(0, MAX_LINES)
    lines[MAX_LINES - 1] = lines[MAX_LINES - 1].replace(/[.,;:!?]+$/, '') + '…'
  }
  return { lines, size: size * grow }
}

function rgba(hex: string, opacityPct: number): string {
  const h = (hex || '').replace('#', '')
  if (h.length !== 6) return hex
  const n = parseInt(h, 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${clamp(opacityPct, 100, 0, 100) / 100})`
}

/** cqh for a value given in px of a 1920-tall frame. */
const cq = (px: number): string => `${(px * 100) / 1920}cqh`

export default function BannerPreview({
  style,
  title,
  dragging = false,
  handlers,
  hint
}: {
  style: Required<CaptionStyle>
  /** The words shown: the clip's title, or the person's own words in the style. */
  title: string
  dragging?: boolean
  /** Pointer handlers when the banner can be dragged. */
  handlers?: Pick<
    React.HTMLAttributes<HTMLDivElement>,
    'onPointerDown' | 'onPointerMove' | 'onPointerUp' | 'onPointerCancel'
  >
  hint?: string
}): JSX.Element | null {
  const text = cleanTitle(style.title_banner_text.trim() || title, style.title_banner_uppercase)
  if (!text) return null
  const { lines, size } = bannerLayout(text, style)
  const pad = clamp(style.title_banner_pad, 18, 0, 80)
  const kind = style.title_banner_box
  const box = rgba(style.title_banner_color, style.title_banner_opacity)
  const outline = clamp(style.title_banner_outline, 0, 0, 16)
  const shadow = clamp(style.title_banner_shadow, 0, 0, 16)
  const shadowColour = style.title_banner_shadow_color || 'rgba(0,0,0,0.5)'
  const fade = Boolean(style.title_banner_gradient)
  const fadeStops = [style.title_banner_text_color, style.title_banner_gradient_mid, style.title_banner_gradient].filter(
    Boolean
  )
  const letters: React.CSSProperties = {
    fontFamily: `'${style.title_banner_font}', sans-serif`,
    fontSize: cq(size),
    lineHeight: LINE,
    fontWeight: 700,
    fontStyle: style.title_banner_italic ? 'italic' : 'normal',
    letterSpacing: cq(clamp(style.title_banner_spacing, 0, -4, 24)),
    whiteSpace: 'nowrap'
  }
  // The box layer and the words layer lie exactly on top of each other, the
  // words above: a box never covers a letter (the burn does the same).
  const boxes =
    kind === 'none' ? null : kind === 'block' ? (
      <div
        aria-hidden
        className="absolute"
        style={{ inset: `-${cq(pad)}`, background: box }}
      />
    ) : (
      <div aria-hidden className="absolute inset-0 flex flex-col items-center">
        {lines.map((line, i) => (
          <div key={i} style={{ ...letters, color: 'transparent' }}>
            {/* Inline padding paints the box out without moving the lines,
                as the burn's box round each line does. */}
            <span style={{ background: box, padding: `${cq(pad)} ${cq(pad)}` }}>
              {line}
            </span>
          </div>
        ))}
      </div>
    )
  return (
    <div
      className={`absolute select-none ${handlers ? (dragging ? 'cursor-grabbing' : 'cursor-grab') : ''}`}
      title={hint}
      style={{
        left: `${style.title_banner_x}%`,
        top: `${style.title_banner_y}%`,
        transform: `translate(-50%, -50%) rotate(${-clamp(style.title_banner_tilt, 0, -20, 20)}deg)`,
        touchAction: 'none',
        outline: dragging ? '1px dashed rgba(255,255,255,0.8)' : undefined,
        pointerEvents: handlers ? 'auto' : 'none'
      }}
      {...handlers}
    >
      <div className="relative">
        {boxes}
        <div className="relative flex flex-col items-center">
          {lines.map((line, i) => (
            <div key={i} className="relative">
              <div
                style={{
                  ...letters,
                  color: fade ? fadeStops[Math.floor(fadeStops.length / 2)] : style.title_banner_text_color,
                  WebkitTextStroke: outline > 0 ? `${cq(outline * 2)} ${style.title_banner_outline_color}` : undefined,
                  paintOrder: 'stroke fill',
                  textShadow: shadow > 0 ? `${cq(shadow)} ${cq(shadow)} 0 ${shadowColour}` : undefined
                }}
              >
                {line}
              </div>
              {fade && (
                // The fade over the outlined letters, as the burn lays its
                // bands over one outline: across the capitals of each line.
                <div
                  aria-hidden
                  className="absolute inset-0"
                  style={{
                    ...letters,
                    color: 'transparent',
                    backgroundImage: `linear-gradient(to bottom, ${fadeStops
                      .map((c, k) => `${c} ${22 + (56 * k) / (fadeStops.length - 1)}%`)
                      .join(', ')})`,
                    WebkitBackgroundClip: 'text',
                    backgroundClip: 'text'
                  }}
                >
                  {line}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
