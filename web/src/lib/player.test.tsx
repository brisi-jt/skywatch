import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlayerProvider, usePlayer, type PlayerClip } from "./player";

const clips: PlayerClip[] = [
  { id: 1, title: "one", subtitle: "a" },
  { id: 2, title: "two", subtitle: "b", interesting: true },
  { id: 3, title: "three", subtitle: "c" },
];

const created: HTMLAudioElement[] = [];

beforeEach(() => {
  created.length = 0;
  HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
  HTMLMediaElement.prototype.pause = vi.fn();
  const RealAudio = window.Audio;
  vi.stubGlobal(
    "Audio",
    function AudioSpy() {
      const el = new RealAudio();
      created.push(el);
      return el;
    } as unknown as typeof Audio,
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function Harness({ onReach }: { onReach?: (c: PlayerClip) => void }) {
  const player = usePlayer();
  return (
    <div>
      <span data-testid="current">{player.clip?.id ?? "none"}</span>
      <span data-testid="hasNext">{String(player.hasNext)}</span>
      <button onClick={() => player.playQueue(clips, 1)}>play-all</button>
      <button onClick={() => player.next()}>next</button>
      <button onClick={() => player.dismiss()}>dismiss</button>
      {onReach && <span data-testid="reach-wired" />}
    </div>
  );
}

function fireEnded() {
  const audio = created[created.length - 1];
  act(() => {
    audio.dispatchEvent(new Event("ended"));
  });
}

describe("PlayerProvider hands-free queue", () => {
  it("seeds the queue and advances to the next clip when one ends", () => {
    render(
      <PlayerProvider>
        <Harness />
      </PlayerProvider>,
    );

    act(() => screen.getByText("play-all").click());
    expect(screen.getByTestId("current").textContent).toBe("1");
    expect(screen.getByTestId("hasNext").textContent).toBe("true");

    fireEnded();
    expect(screen.getByTestId("current").textContent).toBe("2");

    fireEnded();
    expect(screen.getByTestId("current").textContent).toBe("3");
    expect(screen.getByTestId("hasNext").textContent).toBe("false");
  });

  it("keeps the finished clip in the bar after the queue ends", () => {
    render(
      <PlayerProvider>
        <Harness />
      </PlayerProvider>,
    );
    act(() => screen.getByText("play-all").click());
    fireEnded();
    fireEnded(); // now on clip 3
    fireEnded(); // clip 3 ends → queue exhausted
    // the bar still shows the last clip rather than vanishing
    expect(screen.getByTestId("current").textContent).toBe("3");
  });

  it("dismiss clears the bar", () => {
    render(
      <PlayerProvider>
        <Harness />
      </PlayerProvider>,
    );
    act(() => screen.getByText("play-all").click());
    act(() => screen.getByText("dismiss").click());
    expect(screen.getByTestId("current").textContent).toBe("none");
  });

  it("fires the earcon callback only on advance to an interesting clip", () => {
    const onReach = vi.fn();
    render(
      <PlayerProvider onReachInteresting={onReach}>
        <Harness onReach={onReach} />
      </PlayerProvider>,
    );
    act(() => screen.getByText("play-all").click());
    // clip 1 is the initial, user-initiated play — no earcon
    expect(onReach).not.toHaveBeenCalled();
    fireEnded(); // advance to clip 2 (interesting)
    expect(onReach).toHaveBeenCalledTimes(1);
    expect(onReach.mock.calls[0][0].id).toBe(2);
    fireEnded(); // advance to clip 3 (routine) — no earcon
    expect(onReach).toHaveBeenCalledTimes(1);
  });
});
