"use client";

import { Radio } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import React, { useState } from "react";

import { FirstClipCelebration } from "@/components/first-clip-celebration";
import { NamingDialog } from "@/components/naming-dialog";
import { PlayerBar } from "@/components/player-bar";
import { SettingsDialog } from "@/components/settings-dialog";
import { ThemeToggle, ThemeWash } from "@/components/theme-toggle";
import { useStatus } from "@/lib/api/hooks";
import { usePlayer } from "@/lib/player";
import { useWs } from "@/lib/ws";
import { cn } from "@/lib/utils";

const TABS = [
  { href: "/", label: "Today" },
  { href: "/clips/", label: "Clips" },
  { href: "/station/", label: "Station" },
  { href: "/runbook/", label: "Runbook" },
  { href: "/glossary/", label: "Glossary" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { data: status } = useStatus();
  const { connected } = useWs();
  const { clip } = usePlayer();
  const [settingsOpen, setSettingsOpen] = useState(false);

  const stationName = status?.station_name ?? null;

  return (
    <div className={cn("flex min-h-screen flex-col", clip && "pb-24")}>
      <header className="border-b bg-card">
        <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
          <Link
            href="/"
            className="flex min-h-10 items-center gap-2 font-display text-xl font-semibold tracking-tight"
          >
            <Radio className="size-5 text-interesting" aria-hidden />
            <span>{stationName ?? "skywatch station"}</span>
          </Link>

          <nav aria-label="Main" className="order-last flex w-full gap-1 sm:order-none sm:w-auto sm:flex-1">
            {TABS.map((tab) => {
              const active =
                tab.href === "/" ? pathname === "/" : pathname.startsWith(tab.href.replace(/\/$/, ""));
              return (
                <Link
                  key={tab.href}
                  href={tab.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex min-h-10 items-center rounded-md px-3 text-base font-medium transition-colors",
                    active
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                  )}
                >
                  {tab.label}
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto flex items-center gap-1 sm:ml-0">
            {!connected && (
              <span className="mr-1 rounded-full bg-health-warn-surface px-3 py-1 text-sm text-health-warn">
                reconnecting…
              </span>
            )}
            <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-6">{children}</main>

      <footer className="border-t">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-1 px-4 py-6 text-sm text-muted-foreground sm:px-6">
          <p>powered by skywatch</p>
          <p>
            Receive-only airband monitoring for personal use under the UK Wireless Telegraphy Act.
            Nothing is transmitted, and recordings are not rebroadcast.
          </p>
        </div>
      </footer>

      <NamingDialog stationName={status ? stationName : undefined} />
      <PlayerBar />
      <FirstClipCelebration />
      <ThemeWash />
    </div>
  );
}
