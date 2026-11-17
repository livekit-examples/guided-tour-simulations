from __future__ import annotations

import datetime
from collections.abc import Callable
from zoneinfo import ZoneInfo

from livekit.agents import RunContext, SimulationContext, ToolError, beta

from calendar_api import AvailableSlot, FakeCalendar, SlotUnavailableError, book_or_move

SLOT_DURATION_MIN = 30

# How far ahead the default calendar for an unseeded scenario has openings.
DEFAULT_CALENDAR_DAYS = 14

# The clock the scenarios in scenarios.yaml are authored against (a Friday).
# Every scenario shares this baseline unless it overrides it via userdata `now`.
SIMULATION_NOW = "2026-06-12T09:00:00"


def parse_slot(value: str, tz: ZoneInfo) -> datetime.datetime:
    """Parse an ISO datetime from scenario userdata."""
    return datetime.datetime.fromisoformat(value).replace(tzinfo=tz)


def scenario_now(sim: SimulationContext, *, timezone: str) -> datetime.datetime:
    """The clock to pin for a scenario: its userdata ``now`` when set, else the
    shared :data:`SIMULATION_NOW` baseline the scenarios are authored against."""
    tz = ZoneInfo(timezone)
    return parse_slot(sim.userdata().get("now", SIMULATION_NOW), tz)


def fake_calendar(sim: SimulationContext, *, timezone: str) -> FakeCalendar:
    """Seed a FakeCalendar with the scenario's ``available_slots``, pinned to the
    scenario's clock so its absolute dates stay in the future where intended.

    A scenario that doesn't set ``available_slots`` (such as a scenario
    freshly derived from a session) gets a few openings every weekday for the
    next two weeks instead, from a fixed seed so every run sees the same
    calendar. An explicit empty list means no availability at all.
    """
    tz = ZoneInfo(timezone)
    now = scenario_now(sim, timezone=timezone)
    if (raw_slots := sim.userdata().get("available_slots")) is None:
        # The mocked list_available_slots returns everything on the calendar,
        # so keep this short enough for the agent to summarize out loud.
        return FakeCalendar(
            timezone=timezone, seed=0, now=now, horizon_days=DEFAULT_CALENDAR_DAYS
        )

    slots = [
        AvailableSlot(start_time=parse_slot(s, tz), duration_min=SLOT_DURATION_MIN)
        for s in raw_slots
    ]
    return FakeCalendar(timezone=timezone, slots=slots, now=now)


def tool_mocks(cal: FakeCalendar, tz: ZoneInfo) -> dict[str, Callable]:
    """Tool mocks sharing live state: a booking changes what the mocked
    list_available_slots returns on the next call."""
    slots_map: dict[str, AvailableSlot] = {}

    async def list_available_slots() -> str:
        start = cal.now()
        slots = await cal.list_available_slots(
            start_time=start, end_time=start + datetime.timedelta(days=90)
        )
        slots_map.update({s.unique_hash: s for s in slots})
        return (
            "\n".join(
                f"{s.unique_hash} - {s.start_time.astimezone(tz):%A, %B %d, %Y at %H:%M}"
                for s in slots
            )
            or "No slots available at the moment."
        )

    async def schedule_appointment(ctx: RunContext, slot_id: str) -> str | None:
        if not (slot := slots_map.get(slot_id)):
            raise ToolError(f"error: slot {slot_id} was not found")

        email_result = await beta.workflows.GetEmailTask(
            chat_ctx=ctx.session.current_agent.chat_ctx
        )
        if ctx.speech_handle.interrupted:
            return None

        ctx.disallow_interruptions()

        # the booking is recorded on the calendar itself, so on_session_end and
        # on_simulation_end both read it with no bookkeeping duplicated here
        try:
            moved = await book_or_move(
                cal, slot=slot, attendee_email=email_result.email_address
            )
        except SlotUnavailableError:
            raise ToolError("This slot isn't available anymore") from None
        local = slot.start_time.astimezone(tz)
        if moved:
            was = moved.slot.start_time.astimezone(tz)
            return (
                f"The appointment was moved from {was:%A, %B %d, %Y at %H:%M} "
                f"to {local:%A, %B %d, %Y at %H:%M}. The caller has one appointment."
            )
        return f"The appointment was successfully scheduled for {local:%A, %B %d, %Y at %H:%M}."

    return {
        "list_available_slots": list_available_slots,
        "schedule_appointment": schedule_appointment,
    }
