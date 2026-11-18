import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { live, type LiveLogEntry, type LiveOptions, type LiveSessionStatus } from '../lib/live'
import type { Clip, StudioEvent } from '../lib/types'
import { useEvents } from '../lib/useEvents'
import { t } from '../lib/i18n'

const OPTIONS_KEY = 'live.options'

const KIND_LABEL: Record<string, string> = {
  viewer_clip: 'Viewer clip',
  command: '!clip',
  chat: 'Chat'
}

const TONE: Record<LiveLogEntry['type'], string> = {
  started: 'text-success',
  stopped: 'text-muted',
  moment: 'text-accent',
  queued: 'text-ink',
  skipped: 'text-warn',
  error: 'text-error'
}

function loadOptions(): LiveOptions {
  try {
    return { pre_seconds: 25, post_seconds: 8, min_votes: 3, chat_bursts: true, max_clips: 40,
      ...JSON.parse(localStorage.getItem(OPTIONS_KEY) || '{}') }
  } catch {
    return { pre_seconds: 25, post_seconds: 8, min_votes: 3, chat_bursts: true, max_clips: 40 }
  }
}

function clock(epoch: number): string {
  return new Date(epoch * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function Dot({ on, label }: { on: boolean; label: string }): JSX.Element {
  return (
    <span className="flex items-center gap-1.5 text-sm">
      <span className={`size-2.5 rounded-full ${on ? 'bg-success animate-pulse' : 'bg-error'}`} />
      {label}
    </span>
  )
}

/** Clips made from this session's moments, as their jobs finish. */
function LiveClips({ session, onOpen }: { session: LiveSessionStatus; onOpen?: (videoId: string) => void }): JSX.Element | null {
  const ids = session.log.filter((e) => e.type === 'queued' && e.video_id).map((e) => e.video_id as string)
  const [clips, setClips] = useState<Record<string, Clip | null>>({})
  const key = ids.join(',')
  useEffect(() => {
    let gone = false
    void Promise.all(
      ids.map((id) => api.clips(id).then((rows) => [id, rows[0] ?? null] as const).catch(() => [id, null] as const))
    ).then((rows) => {
      if (!gone) setClips(Object.fromEntries(rows))
    })
    return () => {
      gone = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, session.log.length])
  if (!ids.length) return null
  return (
    <div className="space-y-2">
      <h3 className="font-semibold text-sm">{t('Clips from this live')}</h3>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3">
        {ids
          .slice()
          .reverse()
          .map((id) => {
            const clip = clips[id]
            return (
              <button
                key={id}
                type="button"
                className="card !p-2 text-left space-y-1 hover:border-accent disabled:opacity-60"
                disabled={!clip}
                onClick={() => onOpen?.(id)}
              >
                {clip ? (
                  <video
                    src={api.mediaUrl(clip.id)}
                    className="w-full aspect-[9/16] rounded bg-black object-cover"
                    muted
                    preload="metadata"
                  />
                ) : (
                  <div className="w-full aspect-[9/16] rounded bg-black/40 flex items-center justify-center text-xs text-muted">
                    {t('Rendering…')}
                  </div>
                )}
                <p className="text-xs line-clamp-2">{clip?.title || id}</p>
              </button>
            )
          })}
      </div>
    </div>
  )
}

function SessionCard({
  session,
  onStop,
  onOpen
}: {
  session: LiveSessionStatus
  onStop: () => void
  onOpen?: (videoId: string) => void
}): JSX.Element {
  const moments = session.log.filter((e) => e.type === 'moment').length
  return (
    <section className="card space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="font-semibold text-lg">twitch.tv/{session.channel}</h2>
        {session.stream_title && <span className="text-sm text-muted truncate max-w-md">{session.stream_title}</span>}
        <span className="flex-1" />
        {session.running ? (
          <button type="button" className="btn-ghost" onClick={onStop}>
            {t('Stop')}
          </button>
        ) : (
          <span className="text-sm text-muted">{t('Stopped')}</span>
        )}
      </div>
      <div className="flex items-center gap-x-5 gap-y-2 flex-wrap">
        <Dot on={session.recording} label={t('Recording') + ` (${Math.round(session.buffered_seconds / 60)} min)`} />
        <Dot on={session.chat_connected} label={t('Chat') + ` (${session.chat_per_minute}/min)`} />
        <Dot
          on={session.viewer_clips && !session.viewer_clips_error}
          label={session.viewer_clips ? t('Viewer clips') : t('Viewer clips: connect Twitch in Settings')}
        />
        <span className="text-sm text-muted">
          {moments} {t('moments')} · {session.clips_queued}/{session.max_clips} {t('clips')}
          {session.pending > 0 && ` · ${session.pending} ${t('waiting for the seconds after')}`}
        </span>
      </div>
      {(session.recorder_error || session.chat_error || session.viewer_clips_error) && (
        <p className="text-xs text-warn">
          {[session.recorder_error, session.chat_error, session.viewer_clips_error].filter(Boolean).join(' · ')}
        </p>
      )}
      <LiveClips session={session} onOpen={onOpen} />
      <div className="max-h-56 overflow-y-auto text-sm space-y-1 font-mono">
        {session.log
          .slice()
          .reverse()
          .map((e, i) => (
            <div key={`${e.t}-${i}`} className="flex gap-2">
              <span className="text-muted shrink-0">{clock(e.t)}</span>
              {e.kind && <span className="text-muted shrink-0">[{t(KIND_LABEL[e.kind] ?? e.kind)}]</span>}
              <span className={TONE[e.type] ?? ''}>{e.text}</span>
            </div>
          ))}
      </div>
    </section>
  )
}

/** Live clipping: clips made while a channel is still live, from what its
 *  audience does (chat bursts, !clip, clips viewers make). The work happens
 *  in the engine (live/); this page starts, stops and shows it. */
export default function Live({ onOpenInStudio }: { onOpenInStudio?: (videoId: string) => void }): JSX.Element {
  const [sessions, setSessions] = useState<LiveSessionStatus[]>([])
  const [channel, setChannel] = useState('')
  const [options, setOptions] = useState<LiveOptions>(loadOptions)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setSessions((await live.status()).sessions)
    } catch {
      /* engine starting */
    }
  }, [])
  useEffect(() => {
    void refresh()
    const id = setInterval(() => void refresh(), 3000)
    return () => clearInterval(id)
  }, [refresh])
  useEvents((event: StudioEvent) => {
    if ((event.type as string) === 'live' || event.type === 'job') void refresh()
  })

  const set = (patch: LiveOptions): void => {
    const next = { ...options, ...patch }
    setOptions(next)
    try {
      localStorage.setItem(OPTIONS_KEY, JSON.stringify(next))
    } catch {
      /* private window */
    }
  }

  const start = async (): Promise<void> => {
    setError('')
    setBusy(true)
    try {
      await live.start(channel, options)
      setChannel('')
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const num = (key: keyof LiveOptions, label: string, min: number, max: number): JSX.Element => (
    <label className="flex items-center gap-2 text-sm">
      {label}
      <input
        type="number"
        className="input !w-20"
        min={min}
        max={max}
        value={Number(options[key] ?? 0)}
        onChange={(e) => set({ [key]: Math.max(min, Math.min(max, Number(e.target.value) || min)) })}
      />
    </label>
  )

  return (
    <div className="p-6 space-y-5 w-full max-w-5xl">
      <div className="flex items-baseline gap-3 flex-wrap">
        <h1 className="text-xl font-bold">{t('Live clipping')}</h1>
        <p className="text-sm text-muted">
          {t('Clips made while the stream is still live: when chat explodes, viewers type !clip, or someone makes a Twitch clip.')}
        </p>
      </div>

      <section className="card space-y-3">
        <div className="flex gap-2 flex-wrap">
          <input
            className="input !w-80"
            placeholder="twitch.tv/channel"
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && channel.trim() && void start()}
            aria-label={t('Twitch channel')}
          />
          <button type="button" className="btn-accent" disabled={!channel.trim() || busy} onClick={() => void start()}>
            {busy ? t('Starting…') : t('Start clipping live')}
          </button>
        </div>
        <div className="flex items-center gap-x-5 gap-y-2 flex-wrap">
          {num('pre_seconds', t('Seconds before'), 5, 90)}
          {num('post_seconds', t('Seconds after'), 2, 30)}
          {num('min_votes', t('!clip votes'), 1, 20)}
          {num('max_clips', t('Max clips'), 1, 200)}
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              className="size-4 accent-[#38BDF8]"
              checked={options.chat_bursts !== false}
              onChange={(e) => set({ chat_bursts: e.target.checked })}
            />
            {t('Clip when chat explodes')}
          </label>
        </div>
        <p className="text-xs text-muted">
          {t('Chat and the video are read without logging in. Clips viewers make on Twitch need your Twitch account connected in Settings.')}
        </p>
        {error && <p className="text-sm text-error">{error}</p>}
      </section>

      {sessions
        .slice()
        .sort((a, b) => Number(b.running) - Number(a.running) || b.started - a.started)
        .map((s) => (
          <SessionCard
            key={s.channel}
            session={s}
            onOpen={onOpenInStudio}
            onStop={() => void live.stop(s.channel).then(refresh).catch((e) => setError(String(e)))}
          />
        ))}
    </div>
  )
}
