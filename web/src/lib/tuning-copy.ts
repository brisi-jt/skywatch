/**
 * Every word on the tuning bench, in one place.
 *
 * Voice: the runbook's — warm, plain English, written for someone meeting
 * radio jargon for the first time. If a sentence needs the glossary to make
 * sense, rewrite the sentence.
 */

export interface ExplainItem {
  /** Matches the numbered badge shown on the bench while the overlay is up. */
  number: number;
  anchor: "gain" | "squelch" | "strips" | "ppm" | "meters" | "apply" | "deep-tune";
  title: string;
  body: string;
}

export const EXPLAIN_ITEMS: ExplainItem[] = [
  {
    number: 1,
    anchor: "gain",
    title: "Gain — the radio's volume knob",
    body:
      "How hard the radio amplifies everything it hears — voices and static " +
      "alike. Too low and distant aircraft vanish into silence; too high and " +
      "the static floor rises until it drowns them out. The fader clicks " +
      "between the real steps the tuner chip supports, so every position is " +
      "one the hardware can actually do.",
  },
  {
    number: 2,
    anchor: "squelch",
    title: "Squelch — when is a sound worth recording?",
    body:
      "The station records only when a signal rises this many decibels above " +
      "the background static. The amber line on each meter is that bar. Set " +
      "it too low and the archive fills with empty hiss; too high and quiet, " +
      "distant calls are missed. Watch the meters: the bar should sit " +
      "comfortably above where the level idles and below where voices peak.",
  },
  {
    number: 3,
    anchor: "strips",
    title: "One strip per frequency",
    body:
      "Each frequency the station listens to gets its own channel strip, like " +
      "one slice of a mixing desk. Most strips follow the station-wide " +
      "squelch. If one frequency is noisier than the rest — a distant tower, " +
      "a scratchy band edge — drag its own amber line to give just that " +
      "channel a different bar. A strip with its own setting shows an " +
      "override tag and a chip to put it back.",
  },
  {
    number: 4,
    anchor: "ppm",
    title: "Frequency trim (ppm)",
    body:
      "The dongle's internal clock runs a whisker fast or slow, so every " +
      "frequency it tunes is off by the same tiny fraction — measured in " +
      "parts per million. If voices sound slightly off or signals sit at the " +
      "edge of their channel, a few clicks here recentres everything at " +
      "once. Most dongles want a correction within about ten either way.",
  },
  {
    number: 5,
    anchor: "meters",
    title: "The meters",
    body:
      "Each bar shows how far the strongest sound on that frequency currently " +
      "rises above its background static — the same number squelch compares " +
      "against. The radio reports fresh figures every fifteen seconds, so the " +
      "meters breathe rather than flicker. “Opens” counts how many " +
      "times squelch has let a transmission through since the radio started.",
  },
  {
    number: 7,
    anchor: "deep-tune",
    title: "Deep tune — the spectrum scope",
    body:
      "A live picture of the whole slice of radio dial the station watches: " +
      "peaks are transmissions, the flat carpet underneath is the static " +
      "floor. The radio can only do one job at a time, so opening the scope " +
      "stops recording until you leave — the amber banner keeps count. Use " +
      "it to see exactly where signals sit before moving the levers.",
  },
  {
    number: 6,
    anchor: "apply",
    title: "Nothing changes until you apply",
    body:
      "Moving a lever only stages the change — the little tags show what " +
      "would change. Apply rewrites the radio's instructions and restarts it, " +
      "which takes the station off the air for about five seconds. Discard " +
      "forgets the staged changes. Once you're happy with a setup, save it as " +
      "the station defaults so every reset chip brings you back here.",
  },
];

export interface WalkthroughStop {
  anchor: "gain" | "squelch" | "strips" | "apply";
  title: string;
  body: string;
}

export const WALKTHROUGH_STOPS: WalkthroughStop[] = [
  {
    anchor: "gain",
    title: "Start with gain",
    body:
      "This fader is the radio's volume knob — it amplifies everything, " +
      "voices and static together. It clicks between the steps the tuner " +
      "hardware really has. Nothing you move takes effect yet.",
  },
  {
    anchor: "squelch",
    title: "Then squelch",
    body:
      "The amber line on each meter decides when a sound is worth recording: " +
      "the signal must rise that far above the background static. Drag the " +
      "line, or tap it and use the arrow keys.",
  },
  {
    anchor: "strips",
    title: "One strip per frequency",
    body:
      "Every frequency gets its own strip with a live meter. Strips normally " +
      "share the station-wide squelch, but you can drag any strip's line to " +
      "give that one frequency its own bar — handy for a noisy channel.",
  },
  {
    anchor: "apply",
    title: "Apply when ready",
    body:
      "Levers only stage changes. When you press Apply, the station goes off " +
      "the air for about five seconds while the radio restarts with your new " +
      "settings. Every lever has a reset chip if you want to step back.",
  },
];

export const CONTEXT_CARDS = [
  {
    title: "Centre frequency",
    body:
      "The single spot the radio parks on so that every active frequency " +
      "fits inside its listening window. The station works it out from " +
      "whichever frequencies are switched on — there's nothing to set.",
  },
  {
    title: "Sample rate",
    body:
      "How fast the radio takes snapshots of the airwaves, which fixes the " +
      "window's width at 2.56 MHz. It's part of the radio's design, not a " +
      "lever.",
  },
  {
    title: "Mode",
    body:
      "Multichannel records every active frequency at once; scan hops " +
      "between them one at a time. The station picks based on whether the " +
      "active frequencies fit in one window.",
  },
] as const;

export const BENCH_COPY = {
  pageTitle: "Tuning bench",
  pageLead:
    "The station's levers, live. Move anything freely — nothing changes on " +
    "air until you apply.",
  explainToggle: "What do these do?",
  explainClose: "Back to the bench",
  explainFooterNote: "Want the tour again?",
  explainFooterAction: "Replay the walkthrough",

  applyButton: "Apply — station off-air ~5 seconds",
  applying: "Retuning — the station is off the air for a few seconds…",
  discardButton: "Discard",
  saveBaselineButton: "Save these as the station defaults",
  baselineSaved: "Saved — the reset chips now return here.",
  applied: "Applied — the station is back on the air.",
  appliedNoRestart:
    "Saved — but the radio could not be restarted, so the old values are " +
    "still on the air:",
  applyDeepTuneConflict:
    "The receiver is busy with a deep tune session right now. Finish that " +
    "session, then apply.",
  applyFailed: "The station could not apply those settings.",
  unsavedWarning:
    "You have staged tuning changes that haven't been applied. Leave and lose them?",

  replayNote:
    "This station is replaying old recordings rather than listening with a " +
    "radio, so there is nothing to tune — the levers are shown for " +
    "reference, and Apply is switched off.",
  noStatsYet: "No live readings yet — the radio reports its first figures shortly after starting.",
  metersPaused:
    "Meters paused — the radio hasn't reported for over a minute. The last " +
    "figures are hidden rather than shown stale.",
  noActiveFrequencies:
    "No frequencies are switched on, so there are no channel strips to show. " +
    "Turn one on from the Station page.",

  inheritsDefault: "station default",
  overrideTag: "override",
  resetChipTitle: "Reset to default",

  walkthroughSkip: "Skip the tour",
  walkthroughNext: "Next",
  walkthroughBack: "Back",
  walkthroughDone: "Finish",
  walkthroughIntro: "First time at the bench? Four quick stops.",

  entryCardTitle: "Tuning bench",
  entryCardBody: "Gain, squelch and frequency trim, with live signal meters.",
  entryCardAction: "Open the tuning bench",
} as const;

export const DEEP_TUNE_COPY = {
  sectionTitle: "Deep tune",
  sectionLead:
    "A live spectrum scope: the whole slice of dial the station watches, " +
    "drawn a couple of times a second, with each active frequency marked. " +
    "The radio can only do one job at a time, so the station stops " +
    "recording while the scope is open.",
  openButton: "Open the scope…",

  confirmTitle: "Stop recording and open the scope?",
  confirmBody:
    "The station stops recording while Deep Tune is open — any radio calls " +
    "during that time are missed. The scope closes itself after ten minutes " +
    "without you touching anything, and recording restarts the moment it " +
    "closes.",
  confirmAction: "Stop recording and open",
  confirmCancel: "Keep recording",

  starting: "Opening the scope — taking the station off the air…",
  unavailableLead: "The scope can't open right now.",

  offAirBanner: "Off the air — Deep Tune has the radio.",
  offAirElapsed: "off air for",
  exitButton: "Exit — restart recording",
  exiting: "Closing the scope and restarting the radio…",

  idleWarning:
    "Still there? Deep Tune closes itself in about a minute and recording " +
    "restarts. Touch any lever — or press Keep going — to stay.",
  keepGoing: "Keep going",

  resumedRequested: "Back on the air — the radio is recording again.",
  resumedIdle:
    "Deep Tune closed itself after ten quiet minutes, and the radio is " +
    "recording again.",
  resumedConnectionLost:
    "Deep Tune closed because the dashboard lost touch with the station; " +
    "the radio is recording again.",
  resumedError:
    "The scope hit a problem and closed; the radio is recording again.",

  noiseFloorLabel: "static floor",
  scopeSummaryLead: "Spectrum readings:",
  outsideWindow: "outside the window",
} as const;
