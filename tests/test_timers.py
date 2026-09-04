from discord_overlay.timers import TimerManager, render_template
from discord_overlay.triggers import Trigger, TriggerCondition, TriggerMatch


def _trigger(**values):
    defaults = dict(id="trigger-1", name="Curse", overlay_enabled=True, overlay_text="{spell} on {target}",
                    timer_seconds=12, timer_key_template="{target}", ending_soon_seconds=3,
                    conditions=[TriggerCondition("curse")])
    defaults.update(values)
    return Trigger(**defaults)


def _match(target="Raan"):
    return TriggerMatch("trigger-1", "Curse", "builtin:Alert", 0.8, "Curse lands",
                        captures={"target": target, "spell": "Withering Curse"})


def test_templates_use_captures_builtins_and_case_insensitive_names():
    trigger = _trigger()
    assert render_template("{trigger}: {spell} -> {target}", trigger, _match()) == "Curse: Withering Curse -> Raan"
    match = TriggerMatch("trigger-1", "Curse", "", 0.8, "Curse lands", captures={"s1": "Raan", "$1": "Withering Curse"})
    assert render_template("{S1}: {$1}", trigger, match) == "Raan: Withering Curse"
    assert render_template("{missing} {text}", trigger, _match()) == "{missing} Curse lands"
    assert render_template("{bad", trigger, _match()) == "{bad"


def test_target_key_creates_independent_timers():
    manager = TimerManager()
    trigger = _trigger()
    assert manager.start(trigger, _match("Raan"), now=10) is not None
    assert manager.start(trigger, _match("Klog"), now=11) is not None
    assert {timer.key for timer in manager.timers.values()} == {"Raan", "Klog"}


def test_overlay_disabled_trigger_starts_no_timer():
    assert TimerManager().start(_trigger(overlay_enabled=False), _match(), now=10) is None


def test_timer_carries_overlay_preferences_and_board():
    manager = TimerManager(overlay_layout="independent", overlay_size="compact")
    timer = manager.start(_trigger(overlay_opacity=0.65, overlay_geometry="250x80+120+140",
                                   overlay_positions={"Raan": "260x90+500+600"}, timer_board="Mob Respawns"),
                          _match(), now=10)
    assert (timer.overlay_layout, timer.overlay_size, timer.overlay_opacity) == ("independent", "compact", 0.65)
    assert (timer.placement_key, timer.overlay_geometry, timer.timer_board) == ("Raan", "260x90+500+600", "Mob Respawns")


def test_alert_only_timer_hides_bar_and_lasts_five_seconds():
    timer = TimerManager().start(_trigger(timer_seconds=0), _match(), now=10)
    assert not timer.show_bar and timer.ends_at == 15


def test_restart_ignore_replace_and_new_retrigger_behaviors():
    manager = TimerManager()
    trigger = _trigger(retrigger_mode="restart")
    original = manager.start(trigger, _match(), now=10)
    restarted = manager.start(trigger, _match(), now=15)
    assert restarted is original and restarted.ends_at == 27

    trigger.retrigger_mode = "ignore"
    assert manager.start(trigger, _match(), now=16) is None

    trigger.retrigger_mode = "new"
    assert manager.start(trigger, _match(), now=17) is not None
    assert len(manager.timers) == 2

    trigger.retrigger_mode = "replace"
    replacement = manager.start(trigger, _match("Klog"), now=18)
    assert list(manager.timers.values()) == [replacement]


def test_ending_and_expiration_notifications_fire_once():
    manager = TimerManager()
    assert manager.start(_trigger(), _match(), now=10) is not None
    assert manager.tick(now=18.9) == []
    assert [n.kind for n in manager.tick(now=19)] == ["ending"]
    assert manager.tick(now=19.5) == []
    assert [n.kind for n in manager.tick(now=22)] == ["expired"]
    assert not manager.timers


def test_early_end_targets_capture_or_all_when_capture_missing():
    manager = TimerManager()
    trigger = _trigger()
    manager.start(trigger, _match("Raan"), now=10)
    manager.start(trigger, _match("Klog"), now=10)
    assert [n.timer.key for n in manager.end(trigger, _match("Raan"))] == ["Raan"]
    assert [n.timer.key for n in manager.end(trigger, TriggerMatch("trigger-1", "Curse", "", 1, "worn off"))] == ["Klog"]


def test_create_another_ends_oldest_same_name_timer_only():
    manager = TimerManager()
    trigger = _trigger(retrigger_mode="new")
    first = manager.start(trigger, _match("a large rat"), now=10)
    second = manager.start(trigger, _match("a large rat"), now=12)
    assert len(manager.timers) == 2
    assert [n.timer.id for n in manager.end(trigger, _match("a large rat"))] == [first.id]
    assert list(manager.timers) == [second.id]


def test_dismiss_and_clear():
    manager = TimerManager()
    first = manager.start(_trigger(), _match("Raan"), now=10)
    second = manager.start(_trigger(), _match("Klog"), now=11)
    assert manager.dismiss(first.id) is first
    assert list(manager.timers) == [second.id]
    assert manager.dismiss("missing") is None
    manager.clear()
    assert not manager.timers
