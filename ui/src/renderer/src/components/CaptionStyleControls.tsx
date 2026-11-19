import { useEffect, useRef, useState } from 'react'
import type { CaptionStyle } from '../lib/types'
import { t } from '../lib/i18n'
import BannerPreview from './BannerPreview'

/** "Cover only": the title stays on the first frames alone, so it is the
 *  thumbnail and is gone once the clip plays. A tenth of a second is three
 *  frames at 30 fps, enough to survive a re-encode keeping the first frame. */
export const COVER_SECONDS = 0.1

export const DEFAULT_CAPTION_STYLE: Required<CaptionStyle> = {
  font: 'Arial',
  font_size: 84,
  color: '#FFFFFF',
  position: 'bottom',
  caption_y: 77,
  words_per_caption: 3,
  uppercase: true,
  highlight: false,
  highlight_color: '#FFE600',
  second_speaker: false,
  second_speaker_color: '#5CE1FF',
  title_banner: false,
  title_banner_color: '#E01B24',
  title_banner_text_color: '#FFFFFF',
  title_banner_font: 'Impact',
  title_banner_x: 50,
  title_banner_y: 50,
  title_banner_size: 100,
  title_banner_uppercase: true,
  title_banner_text: '',
  title_banner_captions: 'next_to',
  title_banner_seconds: 0,
  title_banner_pad: 18,
  title_banner_box: 'lines',
  title_banner_opacity: 100,
  title_banner_outline: 0,
  title_banner_outline_color: '#000000',
  title_banner_shadow: 0,
  title_banner_italic: false,
  title_banner_spacing: 0,
  title_banner_tilt: 0,
  title_banner_gradient: '',
  title_banner_gradient_mid: '',
  title_banner_shadow_color: '',
  reveal: false
}

/** Ready-made title looks, as video_editor/title_banner.py PRESETS: one
 *  click sets these over the style; everything stays adjustable after. */
export const BANNER_PRESETS: { id: string; label: string; hint: string; style: Partial<CaptionStyle> }[] = [
  {
    id: 'classic',
    label: 'Red box',
    hint: 'White letters in a red box, the default.',
    style: {
      title_banner: true,
      title_banner_font: 'Impact',
      title_banner_box: 'lines',
      title_banner_color: '#E01B24',
      title_banner_text_color: '#FFFFFF',
      title_banner_gradient: '',
      title_banner_gradient_mid: '',
      title_banner_outline: 0,
      title_banner_shadow: 0,
      title_banner_shadow_color: '',
      title_banner_size: 100,
      title_banner_tilt: 0,
      title_banner_italic: false,
      title_banner_spacing: 0,
      title_banner_uppercase: true
    }
  },
  {
    id: 'vice',
    label: 'GTA VI',
    hint: 'Vice City sunset: yellow to pink to purple letters, night-blue outline, pink shadow. Made for thumbnails.',
    style: {
      title_banner: true,
      title_banner_font: 'Anton',
      title_banner_box: 'none',
      title_banner_text_color: '#FFE27A',
      title_banner_gradient_mid: '#FF5FA2',
      title_banner_gradient: '#8B3DFF',
      title_banner_outline: 8,
      title_banner_outline_color: '#140A2E',
      title_banner_shadow: 9,
      title_banner_shadow_color: '#FF2E88',
      title_banner_size: 150,
      title_banner_tilt: 4,
      title_banner_italic: false,
      title_banner_spacing: 2,
      title_banner_uppercase: true
    }
  },
  // The looks below start from LOOK so a click never keeps a gradient, tilt
  // or shadow left over from the previous look.
  {
    id: 'pink-cyan',
    label: 'Pink and cyan',
    hint: 'Light cyan letters in a full pink box, at the top. A favourite saved from the editor.',
    style: look({
      title_banner_font: 'Impact',
      title_banner_box: 'block',
      title_banner_color: '#F547A7',
      title_banner_text_color: '#C5F7F7',
      title_banner_size: 125,
      title_banner_pad: 60,
      title_banner_spacing: 8,
      title_banner_x: 50,
      title_banner_y: 9,
      title_banner_captions: 'keep'
    })
  },
  {
    id: 'news',
    label: 'Breaking news',
    hint: 'Black letters on a yellow box: reads at a glance, like a news alert.',
    style: look({
      title_banner_font: 'Anton',
      title_banner_box: 'block',
      title_banner_color: '#FFD400',
      title_banner_text_color: '#111111',
      title_banner_size: 115,
      title_banner_pad: 30,
      title_banner_spacing: 2
    })
  },
  {
    id: 'clean',
    label: 'Clean white',
    hint: 'Black letters in a white box round each line, simple and tidy.',
    style: look({
      title_banner_font: 'Montserrat Black',
      title_banner_box: 'lines',
      title_banner_color: '#FFFFFF',
      title_banner_text_color: '#111111',
      title_banner_pad: 22
    })
  },
  {
    id: 'outline',
    label: 'Thick outline',
    hint: 'Big white letters with a thick black outline and no box, the YouTuber classic.',
    style: look({
      title_banner_font: 'Montserrat Black',
      title_banner_box: 'none',
      title_banner_text_color: '#FFFFFF',
      title_banner_outline: 10,
      title_banner_outline_color: '#000000',
      title_banner_shadow: 6,
      title_banner_shadow_color: '#000000',
      title_banner_size: 140
    })
  },
  {
    id: 'black-bar',
    label: 'Black bar',
    hint: 'White letters on a see-through black bar: goes with any video.',
    style: look({
      title_banner_font: 'Bebas Neue',
      title_banner_box: 'block',
      title_banner_color: '#000000',
      title_banner_opacity: 80,
      title_banner_text_color: '#FFFFFF',
      title_banner_size: 135,
      title_banner_pad: 26,
      title_banner_spacing: 3
    })
  },
  {
    id: 'fire',
    label: 'Fire',
    hint: 'Yellow to orange to red letters, dark outline, slightly tilted. Loud and hot.',
    style: look({
      title_banner_font: 'Anton',
      title_banner_box: 'none',
      title_banner_text_color: '#FFF35C',
      title_banner_gradient_mid: '#FF8A00',
      title_banner_gradient: '#E0181B',
      title_banner_outline: 8,
      title_banner_outline_color: '#1A0500',
      title_banner_shadow: 6,
      title_banner_shadow_color: '#000000',
      title_banner_size: 150,
      title_banner_tilt: -3
    })
  },
  {
    id: 'neon',
    label: 'Green neon',
    hint: 'Neon green letters with a glow, no box. Made for gaming.',
    style: look({
      title_banner_font: 'Bebas Neue',
      title_banner_box: 'none',
      title_banner_text_color: '#39FF14',
      title_banner_outline: 6,
      title_banner_outline_color: '#04210A',
      title_banner_shadow: 10,
      title_banner_shadow_color: '#1B8F0A',
      title_banner_size: 160,
      title_banner_spacing: 4
    })
  },
  {
    id: 'purple',
    label: 'Stream purple',
    hint: 'White letters in a purple box round each line, the streaming colour.',
    style: look({
      title_banner_font: 'Montserrat Black',
      title_banner_box: 'lines',
      title_banner_color: '#9146FF',
      title_banner_text_color: '#FFFFFF',
      title_banner_size: 105,
      title_banner_pad: 24
    })
  }
]

/** A look's own values over a neutral start: no gradient, outline, shadow,
 *  tilt or italics unless the look asks for them. Position and where the
 *  captions sit are left as the person set them unless the look says. */
function look(own: Partial<CaptionStyle>): Partial<CaptionStyle> {
  return {
    title_banner: true,
    title_banner_gradient: '',
    title_banner_gradient_mid: '',
    title_banner_outline: 0,
    title_banner_outline_color: '#000000',
    title_banner_shadow: 0,
    title_banner_shadow_color: '',
    title_banner_size: 100,
    title_banner_pad: 18,
    title_banner_opacity: 100,
    title_banner_tilt: 0,
    title_banner_italic: false,
    title_banner_spacing: 0,
    title_banner_uppercase: true,
    ...own
  }
}

// Banner geometry at 1080x1920, as video_editor/title_banner.py lays it out.
const BANNER_FONT = 78
const BANNER_LINE = 1.18
const CAPTION_GAP = 22
const CAPTION_ROOM = 260

/** Where the captions go with the banner on, as title_banner.caption_placement
 *  decides: 'above' / 'below' the box, or null (their own position). */
function captionSide(style: Required<CaptionStyle>): 'above' | 'below' | null {
  if (
    !style.title_banner ||
    style.position === 'top' ||
    style.position === 'custom' ||
    style.title_banner_captions === 'keep'
  )
    return null
  const half = (2 * BANNER_FONT * (style.title_banner_size / 100) * BANNER_LINE + 2 * style.title_banner_pad) / 2
  const top = (style.title_banner_y / 100) * 1920 - half
  return top - CAPTION_GAP >= CAPTION_ROOM ? 'above' : 'below'
}

/** Fonts on every stock Windows install — matches video/captions.py FONTS. */
export const CAPTION_FONTS = [
  'Arial',
  'Arial Black',
  'Impact',
  'Verdana',
  'Tahoma',
  'Trebuchet MS',
  'Segoe UI',
  'Georgia',
  'Comic Sans MS',
  'Courier New',
  'Segoe UI Black',
  'Bahnschrift',
  'Franklin Gothic Medium',
  'Calibri',
  'Candara',
  'Corbel',
  'Cambria',
  'Constantia',
  'Palatino Linotype',
  'Times New Roman',
  'Consolas',
  'Lucida Console',
  'Segoe Print',
  'Segoe Script',
  'Ink Free',
  'Gabriola',
  // Shipped with the app (assets/fonts): the short-form caption classics.
  'Montserrat ExtraBold',
  'Montserrat Black',
  'Bebas Neue',
  'Anton'
]

/** Live example of how the burned-in captions will look (9:16 mock). */
function CaptionExample({
  style,
  onMoveBanner,
  onMoveCaption
}: {
  style: Required<CaptionStyle>
  /** Dragging the banner in the example moves it (x, y in % of the frame). */
  onMoveBanner?: (x: number, y: number) => void
  /** Dragging a hand-placed caption moves it (y in % of the frame). */
  onMoveCaption?: (y: number) => void
}): JSX.Element {
  const frame = useRef<HTMLDivElement>(null)
  const [dragging, setDragging] = useState(false)
  // Show one caption group of exactly words_per_caption words — the same
  // grouping the burn-in uses, so changing the setting changes the example.
  const sample = ['your', 'captions', 'look', 'like', 'this', 'onscreen']
  const words = sample.slice(0, Math.max(1, Math.min(6, style.words_per_caption)))
  const text = style.uppercase ? words.join(' ').toUpperCase() : words.join(' ')
  // Cycle the highlight through the words so the example shows the effect
  // moving, which is the whole point of it.
  const [hot, setHot] = useState(0)
  useEffect(() => {
    if (!style.highlight) return
    const id = setInterval(() => setHot((h) => (h + 1) % words.length), 550)
    return () => clearInterval(id)
  }, [style.highlight, words.length])
  const align =
    style.position === 'top' ? 'items-start' : style.position === 'middle' ? 'items-center' : 'items-end'
  const placed = style.position === 'custom'
  const [movingCaption, setMovingCaption] = useState(false)
  const moveCaptionTo = (e: React.PointerEvent): void => {
    const box = frame.current?.getBoundingClientRect()
    if (!box || !onMoveCaption) return
    const y = Math.round(Math.max(8, Math.min(98, ((e.clientY - box.top) / box.height) * 100)))
    if (y !== style.caption_y) onMoveCaption(y)
  }
  // With the title banner, captions sit right next to its box (see captionSide).
  const side = captionSide(style)
  const grow = style.title_banner_size / 100
  // Half the box's height, % of the frame (two lines, as most titles are).
  const halfPct = ((2 * BANNER_FONT * grow * BANNER_LINE + 2 * style.title_banner_pad) / 2 / 1920) * 100
  const gapPct = (CAPTION_GAP / 1920) * 100

  const moveTo = (e: React.PointerEvent): void => {
    const box = frame.current?.getBoundingClientRect()
    if (!box || !onMoveBanner) return
    const x = Math.round(Math.max(10, Math.min(90, ((e.clientX - box.left) / box.width) * 100)))
    const y = Math.round(Math.max(5, Math.min(95, ((e.clientY - box.top) / box.height) * 100)))
    if (x !== style.title_banner_x || y !== style.title_banner_y) onMoveBanner(x, y)
  }

  const banner = style.title_banner ? (
    <BannerPreview
      style={style}
      title={t('Your clip title goes here')}
      dragging={dragging}
      hint={onMoveBanner ? t('Drag to move the title') : undefined}
      handlers={
        onMoveBanner
          ? {
              onPointerDown: (e) => {
                e.currentTarget.setPointerCapture(e.pointerId)
                setDragging(true)
              },
              onPointerMove: (e) => dragging && moveTo(e),
              onPointerUp: () => setDragging(false),
              onPointerCancel: () => setDragging(false)
            }
          : undefined
      }
    />
  ) : null
  return (
    <div
      ref={frame}
      className={`relative rounded-lg bg-gradient-to-br from-slate-700 via-slate-800 to-slate-900 aspect-[9/16] ${style.title_banner || placed ? 'max-h-72' : 'max-h-44'} mx-auto w-auto flex ${side || placed ? '' : align} justify-center overflow-hidden`}
      style={{ containerType: 'size' }}
      aria-label={t('Caption style example')}
    >
      {banner}
      <p
        className={`text-center px-2 leading-tight select-none ${side || placed ? 'absolute inset-x-0' : 'py-4'} ${
          placed && onMoveCaption ? (movingCaption ? 'cursor-grabbing' : 'cursor-grab') : ''
        }`}
        title={placed && onMoveCaption ? t('Drag to move the captions') : undefined}
        onPointerDown={(e) => {
          if (!placed || !onMoveCaption) return
          e.currentTarget.setPointerCapture(e.pointerId)
          setMovingCaption(true)
        }}
        onPointerMove={(e) => movingCaption && moveCaptionTo(e)}
        onPointerUp={() => setMovingCaption(false)}
        onPointerCancel={() => setMovingCaption(false)}
        style={{
          ...(placed ? { bottom: `${100 - style.caption_y}%`, touchAction: 'none' } : {}),
          ...(side === 'above' ? { bottom: `${100 - style.title_banner_y + halfPct + gapPct}%` } : {}),
          ...(side === 'below' ? { top: `${style.title_banner_y + halfPct + gapPct}%` } : {}),
          fontFamily: `'${style.font}', sans-serif`,
          color: style.color,
          // With the banner: true to scale (84px of a 1920-tall frame), so the
          // two sit as they will. Without it, enlarged to read in the small mock.
          fontSize: style.title_banner || placed
            ? `${(style.font_size * 100) / 1920}cqh`
            : `${(style.font_size / 1920) * 176 * 2.2}px`,
          fontWeight: 700,
          WebkitTextStroke: '0.8px black',
          textShadow: '1px 1px 2px rgba(0,0,0,0.9)'
        }}
      >
        {style.highlight
          ? words.map((w, i) => (
              <span key={i} style={{ color: i === hot ? style.highlight_color : style.color }}>
                {(style.uppercase ? w.toUpperCase() : w) + (i < words.length - 1 ? ' ' : '')}
              </span>
            ))
          : text}
        {/* The other speaker's caption, as it follows the main speaker's:
            the two colours side by side are what is being chosen. */}
        {style.second_speaker && (
          <span className="block" style={{ color: style.second_speaker_color }}>
            {style.uppercase ? 'SECOND SPEAKER' : 'second speaker'}
          </span>
        )}
      </p>
    </div>
  )
}

/** The caption style controls (colour, size, position, words, casing),
 *  shared between the Generate bar (style for all new clips) and the
 *  per-clip caption editor. */
export default function CaptionStyleControls({
  idPrefix,
  style,
  onChange,
  hideWordsPerCaption = false,
  hideSecondSpeaker = false,
  hideTitleBanner = false,
  showTitleText = false
}: {
  idPrefix: string
  style: Required<CaptionStyle>
  onChange: <K extends keyof CaptionStyle>(key: K, value: CaptionStyle[K]) => void
  /** Translated subtitles inherit their grouping from the lines they
   *  replace, so regrouping does nothing there — hide it rather than offer
   *  a control that silently has no effect. */
  hideWordsPerCaption?: boolean
  /** Translated subtitles are burned in one colour, whoever is talking. */
  hideSecondSpeaker?: boolean
  /** Translated subtitles: the banner belongs to the clip, not to them. */
  hideTitleBanner?: boolean
  /** One clip's editor: its banner can say something other than its title.
   *  Not for a whole job, where one text would go on every clip. */
  showTitleText?: boolean
}): JSX.Element {
  return (
    <>
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <label htmlFor={`${idPrefix}-font`} className="label">
            Font
          </label>
          <select
            id={`${idPrefix}-font`}
            className="input mt-1"
            value={style.font}
            style={{ fontFamily: `'${style.font}', sans-serif` }}
            onChange={(e) => onChange('font', e.target.value)}
          >
            {CAPTION_FONTS.map((f) => (
              <option key={f} value={f} style={{ fontFamily: `'${f}', sans-serif` }}>
                {f}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={`${idPrefix}-color`} className="label">
            Text colour
          </label>
          <input
            id={`${idPrefix}-color`}
            type="color"
            className="mt-1 h-9 w-full rounded-lg bg-raised cursor-pointer"
            value={style.color}
            onChange={(e) => onChange('color', e.target.value.toUpperCase())}
          />
        </div>
        <div>
          <label htmlFor={`${idPrefix}-size`} className="label">
            Size ({style.font_size})
          </label>
          <input
            id={`${idPrefix}-size`}
            type="range"
            min={40}
            max={140}
            className="mt-3 w-full accent-[#38BDF8]"
            value={style.font_size}
            onChange={(e) => onChange('font_size', Number(e.target.value))}
          />
        </div>
        <div>
          <label htmlFor={`${idPrefix}-pos`} className="label">
            Position
          </label>
          <select
            id={`${idPrefix}-pos`}
            className="input mt-1"
            value={style.position}
            onChange={(e) => onChange('position', e.target.value as CaptionStyle['position'])}
          >
            <option value="bottom">Bottom</option>
            <option value="middle">Middle</option>
            <option value="top">Top</option>
            <option value="custom">Free (drag it)</option>
          </select>
        </div>
        {style.position === 'custom' && (
          <div className="col-span-2">
            <label htmlFor={`${idPrefix}-cap-y`} className="label">
              Caption height ({style.caption_y}%)
            </label>
            <input
              id={`${idPrefix}-cap-y`}
              type="range"
              min={8}
              max={98}
              className="mt-2 w-full accent-[#38BDF8]"
              value={style.caption_y}
              onChange={(e) => onChange('caption_y', Number(e.target.value))}
            />
          </div>
        )}
        {!hideWordsPerCaption && (
          <div>
            <label htmlFor={`${idPrefix}-words`} className="label">
              Words per caption
            </label>
            <select
              id={`${idPrefix}-words`}
              className="input mt-1"
              value={style.words_per_caption}
              onChange={(e) => onChange('words_per_caption', Number(e.target.value))}
            >
              {[1, 2, 3, 4, 5, 6].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>
      <label className="flex items-center gap-2 cursor-pointer text-sm">
        <input
          type="checkbox"
          className="size-4 accent-[#38BDF8]"
          checked={style.uppercase}
          onChange={(e) => onChange('uppercase', e.target.checked)}
        />
        UPPERCASE captions
      </label>

      <label
        className="flex items-center gap-2 cursor-pointer text-sm"
        title={t(
          'Each word shows up the moment it is said, instead of the whole line appearing ahead of the voice.'
        )}
      >
        <input
          type="checkbox"
          className="size-4 accent-[#38BDF8]"
          checked={style.reveal}
          onChange={(e) => onChange('reveal', e.target.checked)}
        />
        Show words as they&apos;re said
      </label>

      <div className="flex items-center gap-3">
        <label className="flex items-center gap-2 cursor-pointer text-sm">
          <input
            type="checkbox"
            className="size-4 accent-[#38BDF8]"
            checked={style.highlight}
            onChange={(e) => onChange('highlight', e.target.checked)}
          />
          Highlight each word as it&apos;s said
        </label>
        {style.highlight && (
          <input
            type="color"
            aria-label={t('Highlight colour')}
            className="h-7 w-10 rounded-md bg-raised cursor-pointer shrink-0"
            value={style.highlight_color}
            onChange={(e) => onChange('highlight_color', e.target.value.toUpperCase())}
          />
        )}
      </div>

      {!hideSecondSpeaker && (
        <div className="flex items-center gap-3">
          <label
            className="flex items-center gap-2 cursor-pointer text-sm"
            title={t(
              "When two people talk in a clip, the main speaker keeps the text colour and the other person's captions take this one. A clip with one voice looks the same as always."
            )}
          >
            <input
              type="checkbox"
              className="size-4 accent-[#38BDF8]"
              checked={style.second_speaker}
              onChange={(e) => onChange('second_speaker', e.target.checked)}
            />
            Second speaker in another colour
          </label>
          {style.second_speaker && (
            <input
              type="color"
              aria-label={t("Second speaker's colour")}
              className="h-7 w-10 rounded-md bg-raised cursor-pointer shrink-0"
              value={style.second_speaker_color}
              onChange={(e) => onChange('second_speaker_color', e.target.value.toUpperCase())}
            />
          )}
        </div>
      )}

      {!hideTitleBanner && (
        <div className="flex flex-col gap-3">
          <label
            className="flex items-center gap-2 cursor-pointer text-sm"
            title={t(
              "The clip's title in a coloured box on the video, for the whole clip. Drag it in the example to move it. Captions sit right next to it, unless they are set to Top."
            )}
          >
            <input
              type="checkbox"
              className="size-4 accent-[#38BDF8]"
              checked={style.title_banner}
              onChange={(e) => onChange('title_banner', e.target.checked)}
            />
            Title banner on the video
          </label>

          {style.title_banner && (
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <p className="label">Ready-made looks</p>
                <div className="mt-1 flex flex-wrap gap-2">
                  {BANNER_PRESETS.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      className="btn-ghost text-xs"
                      // A swatch of the look itself: its box colour, letters and font.
                      style={{
                        background:
                          p.style.title_banner_box === 'none' ? '#1E293B' : p.style.title_banner_color,
                        color: p.style.title_banner_text_color,
                        fontFamily: `'${p.style.title_banner_font}', sans-serif`,
                        WebkitTextStroke:
                          (p.style.title_banner_outline ?? 0) > 0
                            ? `1px ${p.style.title_banner_outline_color}`
                            : undefined,
                        letterSpacing: '0.02em'
                      }}
                      title={t(p.hint)}
                      onClick={() => {
                        for (const [k, v] of Object.entries(p.style)) {
                          onChange(k as keyof CaptionStyle, v as never)
                        }
                      }}
                    >
                      {t(p.label)}
                    </button>
                  ))}
                </div>
              </div>
              {showTitleText && (
                <div className="col-span-2">
                  <label htmlFor={`${idPrefix}-banner-text`} className="label">
                    Title text
                  </label>
                  <input
                    id={`${idPrefix}-banner-text`}
                    className="input mt-1"
                    maxLength={120}
                    placeholder={t("The clip's title")}
                    value={style.title_banner_text}
                    onChange={(e) => onChange('title_banner_text', e.target.value)}
                  />
                </div>
              )}
              <div className="col-span-2">
                <label htmlFor={`${idPrefix}-banner-font`} className="label">
                  Title font
                </label>
                <select
                  id={`${idPrefix}-banner-font`}
                  className="input mt-1"
                  value={style.title_banner_font}
                  style={{ fontFamily: `'${style.title_banner_font}', sans-serif` }}
                  onChange={(e) => onChange('title_banner_font', e.target.value)}
                >
                  {CAPTION_FONTS.map((f) => (
                    <option key={f} value={f} style={{ fontFamily: `'${f}', sans-serif` }}>
                      {f}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor={`${idPrefix}-banner-bg`} className="label">
                  Banner colour
                </label>
                <input
                  id={`${idPrefix}-banner-bg`}
                  type="color"
                  className="mt-1 h-9 w-full rounded-lg bg-raised cursor-pointer"
                  value={style.title_banner_color}
                  onChange={(e) => onChange('title_banner_color', e.target.value.toUpperCase())}
                />
              </div>
              <div>
                <label htmlFor={`${idPrefix}-banner-fg`} className="label">
                  Title colour
                </label>
                <input
                  id={`${idPrefix}-banner-fg`}
                  type="color"
                  className="mt-1 h-9 w-full rounded-lg bg-raised cursor-pointer"
                  value={style.title_banner_text_color}
                  onChange={(e) => onChange('title_banner_text_color', e.target.value.toUpperCase())}
                />
              </div>
              <div className="col-span-2">
                <label className="flex items-center gap-2 cursor-pointer text-sm">
                  <input
                    type="checkbox"
                    className="size-4 accent-[#38BDF8]"
                    checked={Boolean(style.title_banner_gradient)}
                    onChange={(e) => {
                      onChange('title_banner_gradient', e.target.checked ? '#8B3DFF' : '')
                      if (!e.target.checked) onChange('title_banner_gradient_mid', '')
                    }}
                  />
                  {t('Colour fade on the letters (title colour at the top)')}
                </label>
                {style.title_banner_gradient && (
                  <div className="mt-2 grid grid-cols-2 gap-3">
                    <div>
                      <label className="flex items-center gap-2 cursor-pointer label">
                        <input
                          type="checkbox"
                          className="size-3.5 accent-[#38BDF8]"
                          checked={Boolean(style.title_banner_gradient_mid)}
                          onChange={(e) => onChange('title_banner_gradient_mid', e.target.checked ? '#FF5FA2' : '')}
                        />
                        {t('Middle colour')}
                      </label>
                      {style.title_banner_gradient_mid && (
                        <input
                          type="color"
                          aria-label={t('Middle colour')}
                          className="mt-1 h-9 w-full rounded-lg bg-raised cursor-pointer"
                          value={style.title_banner_gradient_mid}
                          onChange={(e) => onChange('title_banner_gradient_mid', e.target.value.toUpperCase())}
                        />
                      )}
                    </div>
                    <div>
                      <label htmlFor={`${idPrefix}-banner-grad`} className="label">
                        {t('Bottom colour')}
                      </label>
                      <input
                        id={`${idPrefix}-banner-grad`}
                        type="color"
                        className="mt-1 h-9 w-full rounded-lg bg-raised cursor-pointer"
                        value={style.title_banner_gradient}
                        onChange={(e) => onChange('title_banner_gradient', e.target.value.toUpperCase())}
                      />
                    </div>
                  </div>
                )}
              </div>
              <div className="col-span-2">
                <label htmlFor={`${idPrefix}-banner-size`} className="label">
                  Title size ({style.title_banner_size}%)
                </label>
                <input
                  id={`${idPrefix}-banner-size`}
                  type="range"
                  min={50}
                  max={200}
                  step={5}
                  className="mt-2 w-full accent-[#38BDF8]"
                  value={style.title_banner_size}
                  onChange={(e) => onChange('title_banner_size', Number(e.target.value))}
                />
              </div>
              <div>
                <label htmlFor={`${idPrefix}-banner-pad`} className="label">
                  Banner thickness ({style.title_banner_pad})
                </label>
                <input
                  id={`${idPrefix}-banner-pad`}
                  type="range"
                  min={0}
                  max={80}
                  step={2}
                  className="mt-2 w-full accent-[#38BDF8]"
                  value={style.title_banner_pad}
                  onChange={(e) => onChange('title_banner_pad', Number(e.target.value))}
                />
              </div>
              <div>
                <label htmlFor={`${idPrefix}-banner-secs`} className="label">
                  {style.title_banner_seconds === COVER_SECONDS
                    ? `${t('Time on screen')} (${t('cover only')})`
                    : style.title_banner_seconds > 0
                      ? `${t('Time on screen')} (${style.title_banner_seconds}s)`
                      : `${t('Time on screen')} (${t('whole clip')})`}
                </label>
                <input
                  id={`${idPrefix}-banner-secs`}
                  type="range"
                  min={0}
                  max={30}
                  step={0.5}
                  disabled={style.title_banner_seconds === COVER_SECONDS}
                  className="mt-2 w-full accent-[#38BDF8] disabled:opacity-40"
                  value={style.title_banner_seconds}
                  onChange={(e) => onChange('title_banner_seconds', Number(e.target.value))}
                />
                <label className="mt-2 flex items-center gap-2 text-sm text-ink">
                  <input
                    type="checkbox"
                    className="size-4 accent-[#38BDF8]"
                    checked={style.title_banner_seconds === COVER_SECONDS}
                    onChange={(e) => onChange('title_banner_seconds', e.target.checked ? COVER_SECONDS : 0)}
                  />
                  {t('Only on the first frame (cover)')}
                </label>
              </div>
              <div>
                <label htmlFor={`${idPrefix}-banner-x`} className="label">
                  Left / right ({style.title_banner_x}%)
                </label>
                <input
                  id={`${idPrefix}-banner-x`}
                  type="range"
                  min={10}
                  max={90}
                  className="mt-2 w-full accent-[#38BDF8]"
                  value={style.title_banner_x}
                  onChange={(e) => onChange('title_banner_x', Number(e.target.value))}
                />
              </div>
              <div>
                <label htmlFor={`${idPrefix}-banner-y`} className="label">
                  Up / down ({style.title_banner_y}%)
                </label>
                <input
                  id={`${idPrefix}-banner-y`}
                  type="range"
                  min={5}
                  max={95}
                  className="mt-2 w-full accent-[#38BDF8]"
                  value={style.title_banner_y}
                  onChange={(e) => onChange('title_banner_y', Number(e.target.value))}
                />
              </div>
              <div className="col-span-2">
                <label htmlFor={`${idPrefix}-banner-captions`} className="label">
                  Captions with the title
                </label>
                <select
                  id={`${idPrefix}-banner-captions`}
                  className="input mt-1"
                  value={style.title_banner_captions}
                  onChange={(e) =>
                    onChange('title_banner_captions', e.target.value as CaptionStyle['title_banner_captions'])
                  }
                >
                  <option value="next_to">Right next to the title</option>
                  <option value="keep">Where Position puts them</option>
                </select>
              </div>
              <div className="col-span-2">
                <label htmlFor={`${idPrefix}-banner-box`} className="label">
                  Banner style
                </label>
                <select
                  id={`${idPrefix}-banner-box`}
                  className="input mt-1"
                  value={style.title_banner_box}
                  onChange={(e) => onChange('title_banner_box', e.target.value as CaptionStyle['title_banner_box'])}
                >
                  <option value="lines">A box round each line</option>
                  <option value="block">One box round the whole title</option>
                  <option value="none">No box (words only)</option>
                </select>
              </div>
              {style.title_banner_box !== 'none' && (
                <div className="col-span-2">
                  <label htmlFor={`${idPrefix}-banner-opacity`} className="label">
                    Banner opacity ({style.title_banner_opacity}%)
                  </label>
                  <input
                    id={`${idPrefix}-banner-opacity`}
                    type="range"
                    min={0}
                    max={100}
                    step={5}
                    className="mt-2 w-full accent-[#38BDF8]"
                    value={style.title_banner_opacity}
                    onChange={(e) => onChange('title_banner_opacity', Number(e.target.value))}
                  />
                </div>
              )}
              <div>
                <label htmlFor={`${idPrefix}-banner-outline`} className="label">
                  Letter outline ({style.title_banner_outline})
                </label>
                <div className="flex items-center gap-2 mt-2">
                  <input
                    id={`${idPrefix}-banner-outline`}
                    type="range"
                    min={0}
                    max={16}
                    className="w-full accent-[#38BDF8]"
                    value={style.title_banner_outline}
                    onChange={(e) => onChange('title_banner_outline', Number(e.target.value))}
                  />
                  <input
                    type="color"
                    aria-label={t('Outline colour')}
                    className="h-7 w-10 rounded-md bg-raised cursor-pointer shrink-0"
                    value={style.title_banner_outline_color}
                    onChange={(e) => onChange('title_banner_outline_color', e.target.value.toUpperCase())}
                  />
                </div>
              </div>
              <div>
                <label htmlFor={`${idPrefix}-banner-shadow`} className="label">
                  Shadow ({style.title_banner_shadow})
                </label>
                <div className="flex items-center gap-2 mt-2">
                  <input
                    id={`${idPrefix}-banner-shadow`}
                    type="range"
                    min={0}
                    max={16}
                    className="w-full accent-[#38BDF8]"
                    value={style.title_banner_shadow}
                    onChange={(e) => onChange('title_banner_shadow', Number(e.target.value))}
                  />
                  <input
                    type="color"
                    aria-label={t('Shadow colour')}
                    title={t('Shadow colour (solid). Unset: see-through black.')}
                    className="h-7 w-10 rounded-md bg-raised cursor-pointer shrink-0"
                    value={style.title_banner_shadow_color || '#000000'}
                    onChange={(e) => onChange('title_banner_shadow_color', e.target.value.toUpperCase())}
                  />
                </div>
              </div>
              <div>
                <label htmlFor={`${idPrefix}-banner-spacing`} className="label">
                  Letter spacing ({style.title_banner_spacing})
                </label>
                <input
                  id={`${idPrefix}-banner-spacing`}
                  type="range"
                  min={-4}
                  max={24}
                  className="mt-2 w-full accent-[#38BDF8]"
                  value={style.title_banner_spacing}
                  onChange={(e) => onChange('title_banner_spacing', Number(e.target.value))}
                />
              </div>
              <div>
                <label htmlFor={`${idPrefix}-banner-tilt`} className="label">
                  Tilt ({style.title_banner_tilt}°)
                </label>
                <input
                  id={`${idPrefix}-banner-tilt`}
                  type="range"
                  min={-20}
                  max={20}
                  className="mt-2 w-full accent-[#38BDF8]"
                  value={style.title_banner_tilt}
                  onChange={(e) => onChange('title_banner_tilt', Number(e.target.value))}
                />
              </div>
              <label className="flex items-center gap-2 cursor-pointer text-sm">
                <input
                  type="checkbox"
                  className="size-4 accent-[#38BDF8]"
                  checked={style.title_banner_italic}
                  onChange={(e) => onChange('title_banner_italic', e.target.checked)}
                />
                Italic title
              </label>
              <label className="flex items-center gap-2 cursor-pointer text-sm">
                <input
                  type="checkbox"
                  className="size-4 accent-[#38BDF8]"
                  checked={style.title_banner_uppercase}
                  onChange={(e) => onChange('title_banner_uppercase', e.target.checked)}
                />
                UPPERCASE title
              </label>
            </div>
          )}
        </div>
      )}

      <div>
        <p className="label mb-1">Example</p>
        <CaptionExample
          style={hideTitleBanner ? { ...style, title_banner: false } : style}
          onMoveBanner={(x, y) => {
            onChange('title_banner_x', x)
            onChange('title_banner_y', y)
          }}
          onMoveCaption={(y) => onChange('caption_y', y)}
        />
      </div>
    </>
  )
}
