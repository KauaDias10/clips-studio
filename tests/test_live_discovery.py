"""Finding finished livestreams about a topic, and queueing them once a day.

Pinned here: only streams that already ended come back, restricted or short
ones are skipped without failing the search, the most viewed lead, and a topic
watch never queues the same stream twice (across days or across topics).
"""

import json
from datetime import datetime

import pytest

from core.state import StateDB
from server import automation
from sources import live_discovery as ld

NOW = 1_800_000_000.0


def info(vid, *, status="was_live", views=100, duration=7200, age_limit=0,
         availability="public", started=NOW - 3600, title=None):
    return {
        "id": vid, "webpage_url": f"https://www.youtube.com/watch?v={vid}",
        "title": title or f"Stream {vid}", "channel": "Chan", "live_status": status,
        "is_live": status == "is_live", "view_count": views, "duration": duration,
        "age_limit": age_limit, "availability": availability, "release_timestamp": started,
    }


class FakeYouTube:
    """Flat search lists the ids; a full look returns that id's info or raises."""

    def __init__(self, infos):
        self.infos = {i["id"]: i for i in infos}
        self.urls = []

    def __call__(self, url, *, flat, size=0):
        self.urls.append(url)
        if flat:
            return {"entries": [{"id": v, "url": f"https://www.youtube.com/watch?v={v}",
                                 "view_count": i["view_count"]} for v, i in self.infos.items()]}
        vid = url.split("v=")[1]
        if self.infos[vid].get("boom"):
            raise RuntimeError("Video unavailable")
        return self.infos[vid]


def find(infos, **kw):
    return ld.find_top_lives("elden ring", extract=FakeYouTube(infos), clock=lambda: NOW, **kw)


def test_only_finished_streams_are_kept():
    found = find([info("a" * 11), info("b" * 11, status="is_live"), info("c" * 11, status="is_upcoming"),
                  info("d" * 11, status="post_live"), info("e" * 11, status="not_live")])
    assert [f.url.split("v=")[1] for f in found] == ["a" * 11]


def test_restricted_short_old_and_unreadable_are_skipped_not_fatal():
    ok = info("a" * 11)
    boom = {**info("f" * 11), "boom": True}
    found = find([
        info("b" * 11, age_limit=18), info("c" * 11, availability="subscriber_only"),
        info("d" * 11, duration=600), info("e" * 11, started=NOW - 3 * 86400), boom, ok])
    assert [f.url.split("v=")[1] for f in found] == ["a" * 11]


def test_sorted_by_views_and_limited():
    found = find([info("a" * 11, views=5), info("b" * 11, views=500), info("c" * 11, views=50)], limit=2)
    assert [f.view_count for f in found] == [500, 50]
    assert found[0].channel == "Chan" and found[0].duration_s == 7200 and found[0].reason_skipped is None


def test_search_url_sorts_today_by_views_without_the_on_air_filter():
    assert "sp=CAMSAggC" in ld.search_url("elden ring")  # views, today; no "Live" (= on air now)
    assert "sp=CAMSAggD" in ld.search_url("elden ring", max_age_hours=72)
    assert "search_query=elden%20ring" in ld.search_url("elden ring")


def test_unsupported_platform_and_empty_query_are_refused():
    with pytest.raises(ValueError):
        ld.find_top_lives("x", platforms=("twitch",), extract=FakeYouTube([]))
    with pytest.raises(ValueError):
        ld.find_top_lives("  ", extract=FakeYouTube([]))


def test_failed_search_gives_empty_not_an_error():
    def broken(url, *, flat, size=0):
        raise RuntimeError("network down")
    assert ld.find_top_lives("x", extract=broken) == []


# ---- the topic watch ---------------------------------------------------------


class Broadcaster:
    def publish(self, event):
        pass


class Worker:
    def notify(self):
        pass


def lives(*ids):
    return [ld.FoundLive(url=f"https://www.youtube.com/watch?v={i * 11}", title=f"T{i}", view_count=10)
            for i in ids]


def make(tmp_path, results):
    db_path = tmp_path / "state.db"
    calls = []

    def discover(query, **kw):
        calls.append((query, kw))
        return results()

    clock = {"now": datetime(2026, 9, 24, 10, 0).timestamp()}
    watcher = automation.ChannelWatcher(
        lambda: StateDB(db_path), feed=None, worker=Worker(), broadcaster=Broadcaster(),
        clock=lambda: clock["now"], discover=discover)
    d = StateDB(db_path)
    d.set_flag(automation.ENABLED_KEY, "1")
    automation.save_topics(d, [{"id": "t1", "query": "elden ring", "platforms": ["youtube"],
                                "per_day": 2, "clips_per_video": 4, "enabled": True,
                                "options": {"preset": "standard"}, "last_run_day": ""}])
    return watcher, d, calls, clock


def queued_ids(d):
    return sorted(r["video_id"] for r in d.conn.execute("SELECT video_id FROM jobs"))


def test_topic_queues_per_day_and_never_twice(tmp_path):
    watcher, d, calls, clock = make(tmp_path, lambda: lives("a", "b", "c"))
    assert watcher.run_topic(d, "t1")["queued"] == 2
    assert queued_ids(d) == ["a" * 11, "b" * 11]
    payload = json.loads(d.conn.execute("SELECT payload FROM jobs").fetchone()[0])
    assert payload["max_clips"] == 4

    # The next day the same three come back: only the unseen one is queued.
    clock["now"] += 86400
    assert watcher.run_topic(d, "t1")["queued"] == 1
    assert queued_ids(d) == ["a" * 11, "b" * 11, "c" * 11]
    clock["now"] += 86400
    assert watcher.run_topic(d, "t1")["queued"] == 0


def test_topic_runs_once_a_day_and_respects_run_hour(tmp_path):
    watcher, d, calls, clock = make(tmp_path, lambda: lives("a"))
    topic = automation.load_topics(d)[0]
    assert automation.topic_due(topic, clock["now"])
    assert not automation.topic_due({**topic, "run_hour": 18}, clock["now"])
    watcher.run_topic(d, "t1")
    topic = automation.load_topics(d)[0]
    assert not automation.topic_due(topic, clock["now"])
    assert automation.topic_due(topic, clock["now"] + 86400)
    assert not automation.topic_due({**topic, "enabled": False}, clock["now"] + 86400)


def test_topic_that_fails_does_not_stop_tick(tmp_path):
    def boom():
        raise RuntimeError("yt-dlp exploded")
    watcher, d, calls, clock = make(tmp_path, boom)
    watcher.tick()
    topic = automation.load_topics(StateDB(tmp_path / "state.db"))[0]
    assert "exploded" in topic["last_error"] and topic["retry_at"] > clock["now"]
