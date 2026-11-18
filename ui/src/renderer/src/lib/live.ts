import { API_BASE } from './api'
import { sessionSecret } from './plugins'
import type { CaptionStyle, GamingSettings } from './types'

export interface LiveLogEntry {
  t: number
  type: 'started' | 'stopped' | 'moment' | 'queued' | 'skipped' | 'error'
  text: string
  at?: number
  kind?: 'chat' | 'command' | 'viewer_clip' | 'audio'
  job_id?: number
  video_id?: string
}

export interface LiveSessionStatus {
  channel: string
  /** 'twitch:alanzoka', 'kick:xqc', 'youtube:@handle': what start/stop go by. */
  key: string
  platform: 'twitch' | 'kick' | 'youtube'
  /** 'twitch.tv/alanzoka', 'kick.com/xqc', 'youtube.com/@handle' */
  label: string
  page_url: string
  audio_peaks: boolean
  /** The one video every clip of this live goes into. */
  group_id: string
  running: boolean
  started: number
  recording: boolean
  buffered_seconds: number
  recorder_error: string
  chat_connected: boolean
  chat_error: string
  chat_per_minute: number
  stream_title: string
  pending: number
  clips_queued: number
  max_clips: number
  viewer_clips: boolean
  viewer_clips_error: string
  log: LiveLogEntry[]
}

export interface LiveOptions {
  pre_seconds?: number
  post_seconds?: number
  min_votes?: number
  chat_bursts?: boolean
  /** Clip loud stretches of the stream (default: on for Kick and YouTube). */
  audio_peaks?: boolean
  max_clips?: number
  captions?: boolean
  caption_style?: CaptionStyle
  gaming?: boolean
  gaming_layout?: GamingSettings
}

async function call<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (method !== 'GET') {
    const secret = await sessionSecret()
    if (!secret) throw new Error('Live clipping needs the desktop app.')
    headers['X-Clips-Kitty-Session'] = secret
  }
  const response = await fetch(`${API_BASE}/live${path}`, {
    method,
    headers,
    ...(body === undefined ? {} : { body: JSON.stringify(body) })
  })
  if (!response.ok) {
    const value = await response.json().catch(() => ({}))
    throw new Error(typeof value.detail === 'string' ? value.detail : 'Live clipping could not be reached.')
  }
  return response.json() as Promise<T>
}

export const live = {
  status: () => call<{ sessions: LiveSessionStatus[] }>(''),
  start: (channel: string, options: LiveOptions) =>
    call<LiveSessionStatus>('/start', 'POST', { channel, options }),
  stop: (channel: string) => call<LiveSessionStatus>(`/${encodeURIComponent(channel)}/stop`, 'POST')
}
