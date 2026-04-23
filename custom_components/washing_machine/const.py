"""Constants for the Washing Machine integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "washing_machine"

# Config keys
CONF_POWER_SENSOR = "power_sensor"
CONF_DOOR_SENSOR = "door_sensor"
CONF_NOTIFY_TARGETS = "notify_targets"
CONF_START_POWER_W = "start_power_w"
CONF_START_DURATION_S = "start_duration_s"
CONF_END_POWER_W = "end_power_w"
CONF_END_DURATION_S = "end_duration_s"
CONF_REMINDER_INTERVAL_M = "reminder_interval_m"
CONF_REMINDER_START_HOUR = "reminder_start_hour"
CONF_REMINDER_END_HOUR = "reminder_end_hour"
CONF_ERROR_DURATION_H = "error_duration_h"
CONF_DOOR_OPEN_STATE = "door_open_state"
CONF_STARTING_TOTAL = "starting_total"
CONF_EXTRA_REMINDERS = "extra_reminders"
CONF_EXTRA_THANK_YOU = "extra_thank_you"

# Defaults
DEFAULT_START_POWER_W = 5.0
DEFAULT_START_DURATION_S = 30
DEFAULT_END_POWER_W = 2.0
DEFAULT_END_DURATION_S = 600  # 10 min — machines idle between spin rests
DEFAULT_REMINDER_INTERVAL_M = 60
DEFAULT_REMINDER_START_HOUR = 7
DEFAULT_REMINDER_END_HOUR = 24  # midnight
DEFAULT_ERROR_DURATION_H = 3
DEFAULT_DOOR_OPEN_STATE = "on"

# State enum (stored in coordinator.state)
STATE_IDLE = "idle"
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_ERROR = "error"

# Coordinator tick interval
UPDATE_INTERVAL = timedelta(seconds=10)

# Notification defaults
NOTIFY_TAG = "washing_machine_status"
NOTIFY_ERROR_TAG = "washing_machine_error"
NOTIFY_GROUP = "laundry"

# Data retention (kept in memory + restored)
CYCLE_HISTORY_DAYS = 90  # keep last 90 days of cycle timestamps
UNLOAD_HISTORY_MAX = 200  # keep last 200 unload times

# Reminder messages
REMINDER_MESSAGES = [
    "Hey genius, your laundry is done. Move it to the dryer before it starts fermenting.",
    "Your clothes have been sitting here so long they're applying for residency. Rotate them.",
    "I washed the clothes. Now do your part, slacker.",
    "Reminder: wet laundry doesn't magically walk to the dryer. MOVE IT.",
    "Your laundry is ready. Unlike you, it actually finished something today.",
    "Rotate the laundry before it turns into that smell you pretend you 'don't notice.'",
    "Congratulations! Your laundry is done. Tragically, your motivation is not.",
    "The washer has finished. The dryer awaits. Don't screw this up.",
    "Your clothes are sitting here wet. Again. Because of course they are.",
    "HEY. LAUNDRY. NOW. Before I start leaking out of spite.",
]

THANK_YOU_TIERS = [
    # (loads_today_threshold, message)
    (1, "Laundry has been unloaded. You're amazing!"),
    (2, "TWO LOADS? ONE DAY? Save some for the rest of us."),
    (3, "Three loads? Jeez, did you wash the entire neighborhood's clothes?"),
    (4, "FOUR loads today. Either you have kids or you're running a secret laundromat."),
    (5, "Five loads?! At this point you're just showing off."),
]
THANK_YOU_OVERFLOW = "{n} LOADS?! The washing machine is filing a restraining order."
