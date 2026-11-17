<a href="https://livekit.io/">
  <img src="./.github/assets/livekit-mark.png" alt="LiveKit logo" width="100" height="100">
</a>

# Front Desk: Agent Simulations guided tour

This repository goes with the **Agent Simulations** guided tour. It holds the agent from the tour's demo, the scenarios it runs, and the CI that keeps those scenarios passing. Clone it to follow along, or to start testing your own agent the same way.

Front Desk is a voice agent that books office visits. A caller asks for a time, Front Desk checks the calendar, offers a few openings, collects an email address, and books the visit. It's built with [LiveKit Agents for Python](https://github.com/livekit/agents) and tested with [Agent Simulations](https://docs.livekit.io/testing/simulations/): a simulated caller with a persona and a goal talks to the real agent, and a judge grades whether the call reached the right outcome.

```
 simulated caller  ──▶  Front Desk (your real code)  ──▶  judge
 persona + goal         same prompt and tools,            transcript vs. expectations,
                        calendar seeded per scenario      plus the calendar's end state
```

## What's in here

| Path | What it is |
| --- | --- |
| [`src/agent.py`](src/agent.py) | Front Desk: instructions, tools, session setup, and the end-of-simulation check |
| [`src/calendar_api.py`](src/calendar_api.py) | The calendar: an in-memory fake, or [cal.com](https://cal.com) when `CAL_API_KEY` is set |
| [`src/simulation.py`](src/simulation.py) | Everything simulation-specific: seeding the calendar from a scenario, and the tool mocks |
| [`scenarios.yaml`](scenarios.yaml) | The committed scenario set: 10 callers, from cooperative to stubborn |
| [`phone.yaml`](phone.yaml) | Two happy-path calls for a phone simulation against the deployed agent |
| [`tests/test_agent.py`](tests/test_agent.py) | Turn-level unit tests |
| [`.github/workflows/`](.github/workflows/) | Text simulations on every pull request, audio simulations nightly, and lint |

## Setup

You need:

- The [LiveKit CLI](https://docs.livekit.io/intro/basics/cli/), v2.19 or later (v2.19.3 or later for phone simulations). Check with `lk --version`.
- [uv](https://docs.astral.sh/uv/).
- A [LiveKit Cloud](https://cloud.livekit.io/) project with Agent Observability turned on.

Install dependencies and write your project's credentials to `.env.local`:

```console
uv sync
lk cloud auth
lk app env --write --destination .env.local
```

`lk agent simulate` runs against the CLI's default project, not the one in `.env.local`. Check it with `lk project list`, and switch with `lk project set-default <name>` or pass `--project <name>`.

Front Desk uses [LiveKit Inference](https://docs.livekit.io/agents/models/inference/) for every model (Deepgram Nova 3, Gemma 4 31B, Inworld TTS 2), so it needs no other API keys. Set `CAL_API_KEY` to book into a real cal.com calendar. Without it, Front Desk uses an in-memory calendar with a few random openings each weekday.

## Talk to Front Desk

In your terminal:

```console
lk agent console
```

Connected to LiveKit Cloud, so the [Agent Console](https://docs.livekit.io/testing/agent-console/), a frontend, or a phone number can reach it:

```console
lk agent dev
```

One text turn at a time, with every tool call printed:

```console
lk agent debugger start
lk agent debugger say "Can I come in next Tuesday afternoon?"
lk agent debugger stop
```

## The tour

### 1. A scenario is a caller and an outcome

Each scenario in [`scenarios.yaml`](scenarios.yaml) has three parts:

```yaml
- label: Requested time unavailable, accepts an alternative
  instructions: |-          # the caller: who's calling and what they want
    You are Priya Nair, a nurse coming off a night shift...
    - Ask for an appointment on Monday, June 15 in the morning, around 9 AM.
    - When told mornings are not available, push back once...
  agent_expectations: ...   # the outcome: what the judge grades
    The agent must clearly say the requested morning time is not available,
    without inventing a slot...
  userdata:                 # the end state: the data the agent sees and the booking that must exist
    available_slots:
      - "2026-06-15T14:00:00"
      - "2026-06-15T16:30:00"
    expected_booking: "2026-06-15T14:00:00"
```

`userdata` is what makes a run repeatable. Front Desk reads it through one branch at the top of its entrypoint. Production never takes that branch:

```python
if sim := ctx.simulation_context():
    # seeded from the scenario's available_slots
    cal = simulation.fake_calendar(sim, timezone=TIMEZONE)
    tool_mocks = simulation.tool_mocks(cal, ZoneInfo(TIMEZONE))
...
mock_tools(FrontDeskAgent, tool_mocks, session=session)
```

- **Seeded data.** [`simulation.fake_calendar`](src/simulation.py) builds a calendar holding exactly the scenario's `available_slots`, on a clock pinned to `2026-06-12T09:00` (a Friday). Dates are absolute, so the scenarios grade the same way next year.
- **Mocked tools.** The LLM still sees Front Desk's real tool schemas and still chooses which to call. Only execution is swapped. The mocks share the seeded calendar, so a booking removes that slot from the next listing.
- **End-state check.** The judge reads the transcript. `on_simulation_end` in [`src/agent.py`](src/agent.py) reads the calendar. If `expected_booking` names a slot, exactly that booking must exist, and if it's `null`, nothing may be booked. A mismatch fails the run even when the judge passed it, which catches an agent that says "you're all set" without booking anything.

Scenarios without `expected_booking` are graded on the conversation alone. A scenario without `available_slots`, such as one freshly downloaded from the dashboard, gets a default calendar with two weeks of openings, the same on every run.

### 2. Generate scenarios from code

On day one you don't need a scenario file. The CLI can read the agent's source and write a first set:

```console
lk agent simulate text -n 10
```

This uploads the agent's source to LiveKit Cloud so the generator can read it, and the CLI asks before it does. When the run ends, press `s` to save the scenarios. Generated scenarios are a starting point: read each one, cut what doesn't matter, and sharpen vague expectations before you commit them.

### 3. Run the committed set

```console
lk agent simulate text --scenarios scenarios.yaml
```

The CLI starts Front Desk as a local worker, runs every scenario on LiveKit Cloud, prints a verdict and the judge's notes for each, and links to the run in the dashboard. Both the simulated caller and the judge are LLMs, so CI runs each scenario three times and requires two passes:

```console
lk agent simulate text --scenarios scenarios.yaml --samples 3 --concurrency 5
```

### 4. When you see a bad call, make it a test

The most valuable scenarios come from real calls. In the dashboard, open the call under **Sessions** and click **Turn into a test**. The dashboard derives a simulated caller and pass criteria from the call, and you download them as a scenario file.

A downloaded scenario describes one call. Before you commit it, widen it to the class of calls it represents and sharpen its expectation into the rule you want enforced. If the agent's behavior depends on data, add `userdata` so the run sees the same calendar the caller did, and an `expected_booking` so the end state is graded too. Run it, fix the agent until it passes, and add it to `scenarios.yaml` so the bug can't come back.

The tour's bad call is a caller who pushes back on a full Monday morning until the agent invents a slot that doesn't exist. "Requested time unavailable, accepts an alternative" in `scenarios.yaml` covers exactly that.

### 5. Audio and phone simulations

Text runs tell you whether the agent made the right decisions. Audio runs tell you how it sounded: the simulated caller speaks, listens and interrupts, and the run measures the latency the caller heard, talk-overs and long silences, how the agent handled barge-ins, and whether it heard names, numbers and email addresses correctly.

```console
lk agent simulate audio --scenarios scenarios.yaml
lk agent simulate audio --scenarios scenarios.yaml --background-noise --packet-loss --low-quality-microphone
```

A phone simulation dials Front Desk's real number and talks to the deployed agent over the same SIP path a caller takes:

```console
lk agent simulate audio --scenarios phone.yaml --to +1XXXXXXXXXX --from +1XXXXXXXXXX --trunk ST_xxxx
```

A phone run reaches production, so there's no seeded calendar and no mocked tools. That's why [`phone.yaml`](phone.yaml) accepts any offered time and is graded on the conversation alone. To rehearse it without dialing, run `lk agent simulate audio --scenarios phone.yaml` against your local agent. It needs a phone number routed to the deployed agent (see [Deploy](#deploy)) and an outbound trunk with a caller ID on it.

### 6. Run it in CI

| Workflow | When | Runs |
| --- | --- | --- |
| [`simulations.yml`](.github/workflows/simulations.yml) | Every pull request and merge to `main` | `lk agent simulate text --scenarios scenarios.yaml --samples 3 --concurrency 5` |
| [`simulations-audio.yml`](.github/workflows/simulations-audio.yml) | Nightly at 06:00 UTC, and on demand | `lk agent simulate audio --scenarios scenarios.yaml --concurrency 5` |
| [`ruff.yml`](.github/workflows/ruff.yml) | Every pull request and merge to `main` | `ruff check` and `ruff format --check` |

Text mode is cheap enough for every change, and its LLM requests yield to live traffic on the project. Audio runs in real time and calls STT and TTS on every turn, so it runs on a schedule. The CLI exits non-zero when a scenario fails, so a regression fails the check before it merges. Add `LIVEKIT_URL`, `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` as repository secrets.

### 7. Read a failure

Every run, from a laptop or from CI, shows up under **Simulations** in the dashboard with a score, the issues the judge found, and each scenario's transcript. From the terminal:

```console
lk agent simulate list
lk agent simulate view <run-id>
lk agent simulate export <run-id> > run.json
```

When a scenario fails, decide whether the agent is wrong (fix the agent), the scenario is wrong or vague (fix the expectation), or the simulated world differs from production (fix the seeded data). After a fix, rerun the whole file, not just the scenario you were working on.

## Unit tests

Simulations grade whole conversations. Unit tests pin single turns, such as "asking for tomorrow calls `list_available_slots` and offers only tomorrow's times", and finish in seconds:

```console
uv run pytest
```

## Deploy

```console
lk agent create
```

This builds the [`Dockerfile`](Dockerfile), deploys Front Desk to LiveKit Cloud, and writes the agent's ID into `livekit.toml`. Front Desk registers as `front-desk`, so it joins only rooms it's explicitly dispatched to. To give it a phone number, [create an inbound trunk and a dispatch rule](https://docs.livekit.io/telephony/) that dispatches `front-desk` to each call. Stream logs with `lk agent logs`.

Every real session is scored by a group of built-in judges in `on_session_end` and tagged `lk.success` when an appointment was booked, so bad calls stand out in Agent Observability.

## How this differs from the upstream example

Front Desk began as [`examples/frontdesk`](https://github.com/livekit/agents/tree/main/examples/frontdesk) in `livekit/agents`. This version differs in four ways:

- **One appointment per call.** If the caller changes their mind after a time is booked, booking the new time moves the appointment instead of adding a second one. Without this, "Change of mind before confirming" failed 2 of 3 samples: the caller switched times while giving their email, and both slots were booked.
- **The LiveKit turn detector and noise cancellation** are on, for more natural turn-taking on calls and in audio simulations.
- **It registers as `front-desk`** for explicit dispatch.
- **The LiveKit Playground card is removed.**

## Learn more

- [Agent Simulations](https://docs.livekit.io/testing/simulations/)
- [Run simulations in CI](https://docs.livekit.io/testing/simulations/ci/)
- [Agent Observability](https://docs.livekit.io/testing/observability/)
- [Agent debugger](https://docs.livekit.io/testing/debugger/)
- [Workflows: tasks and handoffs](https://docs.livekit.io/agents/logic/workflows/)

## License

MIT. See [LICENSE](LICENSE).
