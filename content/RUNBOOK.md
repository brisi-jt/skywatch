# Station Runbook

This is the owner's manual for your aviation listening station. The station
is a small laptop with a radio receiver plugged into it. All day, every day,
it listens to the aircraft frequencies around Stansted, records every radio
call it hears, types out what was said, and picks out anything unusual so
you can listen to the good bits later.

You don't need to understand radio, computers, or aviation to run it. This
guide covers the handful of things you might ever need to do, and what to
try when something looks wrong. Anything marked **(remote admin)** is a job
for whoever looks after the station over the network — you can safely skip
those parts.

## Starting and stopping the station

The short version: **you shouldn't need to.** The station starts itself when
the laptop powers on, and restarts itself if anything crashes. If the
station seems stuck, the first fix is the oldest one in the book: restart
the laptop, wait two minutes, and check the dashboard.

If a restart of just the station software is needed, open the Terminal app
and paste these three lines, pressing Return after each:

```
launchctl kickstart -k gui/$(id -u)/com.skywatch.rtl-airband
launchctl kickstart -k gui/$(id -u)/com.skywatch.worker
launchctl kickstart -k gui/$(id -u)/com.skywatch.api
```

Each line restarts one part of the station: the radio recorder, the
processing engine, and the dashboard, in that order.

To switch the station off entirely (for example, before unplugging things):

```
launchctl bootout gui/$(id -u)/com.skywatch.rtl-airband
launchctl bootout gui/$(id -u)/com.skywatch.worker
launchctl bootout gui/$(id -u)/com.skywatch.api
```

And to switch it back on:

```
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.skywatch.rtl-airband.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.skywatch.worker.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.skywatch.api.plist
```

The laptop is set up to keep running with the lid closed while it's plugged
into power. Keep it on the charger.

## The radio dongle

The radio receiver is a small USB stick (an "RTL-SDR dongle") with an
antenna cable coming out of it. It draws its power from the laptop, so
there's nothing to charge or switch on.

Two things matter:

- **Keep it plugged in.** If it's unplugged, the station records nothing and
  the dashboard will say the dongle is missing.
- **Give it air.** The dongle runs warm to the touch. That's normal, but
  don't bury it under papers or cushions.

If the dashboard says the dongle can't be found, unplug it, count to five,
and plug it back in — a different USB port is worth trying too. Then restart
the station (see above).

## The antenna

The antenna is doing the real work, and where you put it matters far more
than any setting.

- **Length:** the telescopic antenna should be extended to roughly **55 to
  60 cm**. That length is tuned to the aircraft band. Fully collapsed or
  fully stretched are both worse.
- **Upright:** the antenna should point straight up.
- **High and by a window:** radio signals from aircraft travel in straight
  lines. A first-floor windowsill beats the ground floor; near the glass
  beats deep inside the room. Metal window frames and thick walls soak up
  the signal, so give it the clearest "view" of the sky you can.
- **Away from the laptop:** keep the antenna at least an arm's length from
  the laptop and other electronics, which leak radio noise of their own.

Aircraft several miles up are easy to hear. The control tower's side of the
conversation is ground-level and much harder — if you hear pilots clearly
but the tower rarely, that's the physics, not a fault.

## Tuning

The settings that decide what gets recorded live in the dashboard: open the
**Station** view and press **Open the tuning bench**. Every lever on the
bench explains itself — the "What do these do?" button lays a plain-English
note over each one — but here is the short version:

- **Gain** is the radio's volume knob at the aerial end — how hard it
  amplifies whatever the antenna picks up, voices and static alike. Too low
  and distant aircraft are missed. Too high and the receiver is deafened by
  strong local signals (see "lots of junk clips" below). The fader clicks
  between the steps the radio's own chip supports.
- **Squelch** is the tripwire that starts a recording. The receiver hears
  faint hiss all the time; squelch says "only record when a signal stands
  out this far above the hiss". Too high and quiet transmissions never trip
  it. Too low and it records bursts of empty static. The amber line on each
  channel's meter is that tripwire, drawn on the same scale the meter moves
  on — and a single noisy channel can be given its own line without
  touching the rest.
- **Frequency trim** corrects the dongle's clock, which runs a whisker fast
  or slow. If signals sit slightly off their frequencies, a few clicks of
  the trim knob recentre everything at once.

Moving levers changes nothing by itself — the bench stages your changes and
shows little tags for what would change. Pressing **Apply** rewrites the
radio's instructions and restarts it, which takes the station **off the air
for about five seconds**. That's the whole cost, and the bench warns you on
the button itself.

The tuning loop, watching the live meters between steps:

1. Start from the saved defaults — every lever has a reset chip that takes
   it there.
2. **No clips at all** on a frequency you know is busy? Lower the squelch
   threshold a couple of points at a time (12 → 10 → 8) and apply, until
   clips appear.
3. **Streams of short, empty, static-only clips?** Raise the squelch
   threshold a couple of points.
4. **Distorted audio, or clips triggering with nobody talking even at high
   squelch?** Lower the gain in steps (33 → 25 → 20). Strong local FM and
   broadcast transmitters can overload the dongle; less gain helps it cope.
5. Change one thing at a time, and give each change ten minutes of real
   traffic before judging it.

When the station sounds right, finish the ritual: press **Save these as the
station defaults**. From then on every reset chip returns to the setup you
blessed, not the factory numbers — so future experiments always have a safe
way home.

**Deep Tune** is the bench's spectrum scope: a live picture of the whole
slice of dial the station watches, with each active frequency marked. The
radio can only do one job at a time, so **the station stops recording while
Deep Tune is open** — it asks before opening, an amber banner counts the
time off the air, and it closes itself after ten quiet minutes. Recording
restarts the moment it closes, whichever way it closes.

One note for the curious **(remote admin)**: the gain and squelch lines in
`config/config.yaml` only seed a brand-new station. After first start, the
dashboard's tuning bench owns these values — editing the file won't change
them.

## Changing which frequencies it listens to

Open the dashboard and go to the **Station** view. Each frequency in the
plan has a switch — turn one on to start recording it, off to stop. The
change takes effect on its own within a few seconds; there's nothing else
to press.

One rule to know about: the receiver can only watch a slice of the radio
dial about 2 MHz wide at any one moment. Frequencies close together (like
Stansted's tower and ground) fit in the slice together; ones far apart
don't. If you switch on a frequency that won't fit alongside the ones
already active, the dashboard will refuse politely — the message names
which frequencies clash and which combination would work. Nothing breaks:
it simply won't start an impossible mix, and you can switch something else
off first to make room.

Some frequencies carry a **VERIFY** badge. That means the number came from
an enthusiast listing and hasn't yet been double-checked against an
official source. Hearing the right traffic on it is the proof; confirming
and clearing the badge is a **(remote admin)** job.

## Where the recordings live

Every recording is an ordinary MP3 file on the laptop, filed by date:

```
data/recordings/2026/07/16/stansted-tower_20260716_143210_123805000.mp3
```

The easiest way in is the dashboard's **Clips** view, which plays them with
their transcripts and tells you which aircraft was probably talking. But
the files are just files — you can open the folder and double-click one.

To keep the disk from filling up, **routine** recordings (ordinary,
everyday radio calls) have their audio deleted after 14 days. The
transcript and details are kept forever. Anything marked **interesting** is
never deleted.

## Backing up

The station can copy its database (all the transcripts and details) plus
the audio of every interesting clip to a folder of your choosing — a USB
stick is perfect. Plug one in, open Terminal, and run:

```
cd ~/skywatch && scripts/backup.sh /Volumes/YOUR-USB-STICK/skywatch-backup
```

(Replace `YOUR-USB-STICK` with the name your stick shows in Finder. If the
station lives somewhere other than `~/skywatch`, use that path instead.)

Run it whenever you think of it. It only copies what's new since last time,
so it's quick after the first run.

## When something looks wrong

### The dashboard says the dongle is missing

The radio USB stick isn't answering. Unplug it, count to five, plug it back
in (try another port), then restart the station. If it's still missing
after a laptop reboot, the dongle may have failed — they're inexpensive to
replace.

### No new clips for hours

First, is that actually odd? Small airfields go quiet for long stretches,
and evenings are slower than mornings. Check a frequency that's rarely
silent for long (Stansted's tower during the day). If a busy frequency
really is producing nothing:

- Check the dashboard's Station view — is the recorder running, and is the
  dongle present?
- Check the antenna hasn't been knocked over, collapsed, or unscrewed.
- If everything looks healthy, the squelch may be set too high to trip —
  that's the tuning loop above, on the dashboard's tuning bench.

### Lots of junk clips — static, buzzing, or music

Bursts of static mean the squelch tripwire is set too sensitive. Buzzing,
garbled audio, or fragments of FM radio or broadcast stations mean a strong
local transmitter is overloading the receiver — the fix is lower gain on
the dashboard's tuning bench (see the Tuning section), and if that's not
enough, a small plug-in "FM band-stop filter" between the antenna and the
dongle (a few pounds, and it removes the FM band before it reaches the
receiver).

### The dashboard says the disk is nearly full

The station protects itself: when free space gets too low it pauses
recording rather than filling the disk, and says so on the dashboard. Free
up space — empty the Trash, clear out the Downloads folder, or delete old
routine recordings from `data/recordings/` (back up first if in doubt).
Recording resumes by itself once space is freed.

### The dashboard won't load at all

The dashboard is served by the station itself, so this usually means the
laptop is asleep or the station is stopped. Check the laptop is on and
plugged in, then restart the station, then reboot the laptop. If it loads
at home but not from afar, the remote connection (Tailscale) needs
attention — that's a **(remote admin)** problem, not yours.

## First-time setup (remote admin)

Setting the station up on a fresh machine, in order:

1. Install [Tailscale](https://tailscale.com) and sign the machine into the
   tailnet, so remote help is possible from step one.
2. Clone the repository and run `scripts/bootstrap.sh` (add `--dry-run`
   first to preview what it will do). It installs dependencies, builds the
   radio software, sets up the database, installs the three launchd
   services, and keeps the laptop awake on mains power.
3. Plug in the dongle and check it answers: `rtl_test -t`.
4. Check the speech-recognition engine loads on this machine:
   `uv run python -c "import faster_whisper"`. If that fails, switch
   `asr.engine: whisper_cpp` in `config/config.yaml` and re-run
   `scripts/bootstrap.sh --with-whisper-cpp`.
5. Place the antenna (see above) and prove you can hear aircraft **before
   trusting the pipeline**: tune a known-busy frequency with `rtl_fm` or an
   app like SDR++ and listen by ear.
6. Verify the frequency plan against current official sources — every
   frequency except the 121.5 guard ships marked VERIFY. Correct any that
   have changed, and mark them verified.
7. Tune gain and squelch from the dashboard's tuning bench (the loop in the
   Tuning section) until transmissions split cleanly into clips, then save
   them as the station defaults.
8. Set `capture.source: live` and `capture.supervisor: launchctl` in
   `config/config.yaml`, restart the services, and watch the first real
   clips appear on the dashboard with transcripts and aircraft matches.
9. Prove it survives: reboot the laptop and confirm everything comes back
   without help, then close the lid and confirm recording continues.
10. Run a first backup, and leave it listening.

## The legal bit

This station **receives only** — it cannot transmit, and nothing about it
interferes with aviation. In the United Kingdom, under the
Wireless Telegraphy Act 2006, it is an offence to disclose the contents of
radio transmissions that were not intended for you, or to act upon them.

In practice: enjoy the recordings yourself, at home, as much as you like —
but **do not rebroadcast, publish, or share them**. No posting clips
online, no passing recordings around. Treat what you overhear as
listening, not news.
