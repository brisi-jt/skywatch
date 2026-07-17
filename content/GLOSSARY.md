# Glossary

The words you'll meet in transcripts, on the dashboard, and in this
station's own labels — in plain English. Terms are alphabetical.

## ADS-B

A system where aircraft continuously broadcast their own position, altitude
and identity as digital data — it's what powers flight-tracking websites.
This station listens to **voice**, not ADS-B: the actual radio
conversations between pilots and controllers. The "probable aircraft" shown
next to a clip comes from matching the clip's time and place against ADS-B
position data collected by others, which is why it's presented as a good
guess rather than a fact.

## Approach

The control position that manages arriving aircraft between the en-route
airways and the final line-up with the runway — descending them, spacing
them out, and sequencing them. Around here that's "Essex Radar", handling
Stansted arrivals. Departures talk to them too, on their way up and out.

## ATIS

Automatic Terminal Information Service — a looped recording an airport
broadcasts continuously, giving the weather, the runway in use, and other
essentials. Pilots listen before they call the controller so the controller
doesn't have to repeat it all. Each new version of the loop is lettered:
"information Alpha", then "Bravo", and so on. An ATIS frequency records the
same message over and over — useful for checking reception, dull to browse.

## Callsign

How an aircraft identifies itself on the radio. Airliners use their
airline's radio name plus a flight code — "Speedbird 472" is a British
Airways flight, "Ryanair 815 Bravo" a Ryanair one. Light aircraft use their
registration, like "Golf Alpha Bravo Charlie Delta". The radio callsign is
what you'll see in transcripts.

## Flight level

Altitude expressed in hundreds of feet on a standard pressure setting:
"flight level 80" is roughly 8,000 feet. Used for higher-altitude flying so
that every aircraft measures altitude against the same reference. Below a
certain height, pilots switch to local pressure (see QNH) and say altitudes
in plain feet.

## Flight number

The commercial code on your ticket and the departure board, like "FR1234".
It is often *not* what's said on the radio — the radio callsign can differ
from the marketed flight number. The station shows its best guess at the
flight number alongside the callsign, clearly marked as a guess.

## Frequency trim (ppm)

A tiny correction for the radio dongle's internal clock, which always runs
a whisker fast or slow. Every frequency the dongle tunes is derived from
that clock, so the whole dial drifts by the same fraction — measured in
parts per million (ppm). A few clicks of the trim knob on the tuning bench
recentre everything at once; most dongles want a correction within about
ten either way.

## Gain

How strongly the receiver amplifies what the antenna picks up — the volume
knob at the aerial end. Too little gain and weak, distant aircraft go
unheard; too much and strong local transmitters overload the receiver and
everything turns to mush. Adjusted from the dashboard's tuning bench; see
the runbook's tuning section for the loop.

## Go-around

An abandoned landing: the aircraft climbs away and comes around to try
again. It sounds dramatic and is occasionally about a real problem, but
it's usually precautionary — the aircraft ahead was slow clearing the
runway, or the approach wasn't quite stable. The station flags go-arounds
as interesting because they're uncommon and worth a listen, not because
they're emergencies.

## Ground

The control position responsible for aircraft moving on the airfield
surface — pushback from the gate and taxiing to or from the runway. Tower
handles the runway itself; Ground handles everything up to it.

## Guard (121.5)

121.500 MHz, the international aeronautical emergency frequency, monitored
worldwide and kept clear for distress calls, lost aircraft, and urgent
relays. Most days it carries only the odd test call or a controller asking
someone to switch frequency. Because any real traffic on guard is unusual,
this station flags every transmission on it as interesting.

## Hold (stack)

A holding pattern: aircraft flying a racetrack-shaped loop in the sky,
queueing for their turn to approach. Each aircraft circles at its own
altitude, stepping down as the queue moves — hence "stack". The Lambourne
(LAM) hold, one of the four main stacks feeding Heathrow, sits almost
directly overhead this station: when you see airliners circling above the
house, that's the stack, and the London Control frequency in the station's
plan is where they're being talked to.

## Mayday

The international spoken distress call, always said three times — "mayday,
mayday, mayday" — declaring grave and imminent danger and taking priority
over all other traffic. Extremely rare in real life. The station treats any
transcript containing it as top-priority interesting, which also means the
occasional false alarm when the transcription mishears something.

## Noise floor

The receiver's constant background hiss — the faint static carpet that is
there even when nobody is transmitting. A real signal has to stand clear of
this floor to be heard at all, which is why the tuning bench measures every
signal by how far above the floor it rises (see SNR), and why the deep tune
scope draws the floor as the flat carpet the peaks grow out of.

## Pan-pan

One step below mayday: "pan pan, pan pan, pan pan" declares an urgent
situation — a sick passenger, a technical fault — that needs priority but
isn't immediately life-threatening. Also rare, also always flagged as
interesting.

## QNH

The local atmospheric pressure setting, given in hectopascals ("QNH one
zero one three"). Pilots dial it into their altimeter so it reads altitude
above sea level correctly — pressure changes with the weather, so
controllers pass the current value constantly. One of the most common
things you'll hear, and completely routine.

## Radar (director)

Around Stansted you'll hear "Essex Radar" and "Stansted Director" — radar
control positions that watch aircraft on screen and steer them by voice.
The Director runs the final sequencing, lining arrivals up one behind
another onto the approach. "Radar" in a callsign just means the controller
is working from a radar picture rather than looking out of a window.

## Readback

When a pilot repeats a clearance back word for word — "descend flight level
80, Speedbird 472" — so the controller can catch any mishearing. Required
for safety-critical instructions, and the reason so much of what you'll
hear sounds like an echo. A transcript that seems to say everything twice
is working exactly as intended.

## SNR (signal-to-noise ratio)

How far a signal stands above the background hiss, in decibels — the one
number most of the station's tuning turns on. The channel meters on the
tuning bench show it live, and the squelch threshold is set on the same
scale: when a frequency's SNR climbs past the threshold, recording opens.
A strong, close transmission might read 40 dB; a faint, distant one just a
few.

## Spectrum

A picture of a slice of the radio dial: frequency runs left to right,
signal strength bottom to top, so every transmission appears as a peak
rising from the noise floor. The tuning bench's Deep Tune scope draws the
station's whole listening window this way, live. (A *waterfall* is the same
picture stacked over time, scrolling like sheet music — flight-deck
software loves them, but the scope here keeps to the live view.)

## Squawk

A four-digit code a controller assigns to an aircraft ("squawk 4271"),
which the aircraft's transponder then broadcasts so it shows against the
right blip on radar. Three codes are reserved and never assigned:
**7700** (general emergency), **7600** (radio failure), and **7500**
(unlawful interference). Hearing any of those three on the air is genuinely
unusual, and the station flags them.

## Squelch

The receiver's tripwire: it mutes the constant background hiss and only
opens — starting a recording — when a signal rises far enough above it.
The squelch threshold decides how far is "far enough". Too high and quiet
transmissions are missed; too low and the station records bursts of empty
static. The amber line on each of the tuning bench's meters is the
threshold — drag it, or use the arrow keys, and apply.

## TCAS

Traffic Collision Avoidance System — equipment on the aircraft that watches
for other aircraft getting too close and, if needed, commands the pilots to
climb or descend ("TCAS resolution advisory", or "RA"). Pilots follow it
immediately, even over a controller's instruction, and report it on the
radio afterwards. A mention on frequency means two aircraft got closer than
the system liked — uncommon and always flagged.

## Tower

The control position that owns the runway: take-off clearances, landing
clearances, and everything in the immediate air around the airfield. What
most people picture as "air traffic control". Stansted Tower is the busiest
voice in this station's default plan.
