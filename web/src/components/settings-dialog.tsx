"use client";

import { Settings2 } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useSaveSettings, useSettings, useStatus } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";

export function SettingsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { data: status } = useStatus();
  const { data: settings } = useSettings();
  const { resolvedTheme, setTheme } = useTheme();
  const save = useSaveSettings();
  const [name, setName] = useState("");
  const [phrases, setPhrases] = useState("");

  useEffect(() => {
    if (open) setName(status?.station_name ?? "");
  }, [open, status?.station_name]);

  useEffect(() => {
    if (open && settings?.watch_phrases) setPhrases(settings.watch_phrases.join("\n"));
  }, [open, settings?.watch_phrases]);

  const parsePhrases = (raw: string): string[] => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const line of raw.split("\n")) {
      const trimmed = line.trim();
      if (trimmed && !seen.has(trimmed)) {
        seen.add(trimmed);
        out.push(trimmed);
      }
    }
    return out;
  };

  const saveWatchPhrases = () => {
    save.mutate({ "classify.watch_phrases": parsePhrases(phrases) });
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || trimmed === status?.station_name) {
      onOpenChange(false);
      return;
    }
    save.mutate({ station_name: trimmed }, { onSuccess: () => onOpenChange(false) });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon" className="size-10" aria-label="Settings">
          <Settings2 className="size-5" />
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">Settings</DialogTitle>
          <DialogDescription className="text-base">
            The station’s name and how the dashboard looks.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-6">
          <div className="flex flex-col gap-2">
            <Label htmlFor="settings-station-name" className="text-base">
              Station name
            </Label>
            <Input
              id="settings-station-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="My Airband Station"
              className="h-11 text-base"
            />
            {save.isError && (
              <p className="text-sm text-health-bad">That name could not be saved — try another.</p>
            )}
          </div>
          <div className="flex flex-col gap-2">
            <span className="text-base font-medium">Theme</span>
            <div className="flex gap-2">
              {(["light", "dark"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setTheme(mode)}
                  className={cn(
                    "min-h-10 flex-1 rounded-md border px-3 text-base capitalize transition-colors",
                    resolvedTheme === mode
                      ? "border-ring bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-accent/60",
                  )}
                >
                  {mode}
                </button>
              ))}
            </div>
          </div>
          <div className="flex flex-col gap-2">
            <span className="text-base font-medium">Text size</span>
            <div className="flex gap-2">
              {(["normal", "large"] as const).map((size) => (
                <button
                  key={size}
                  type="button"
                  aria-pressed={(settings?.text_size ?? "normal") === size}
                  onClick={() => save.mutate({ "display.text_size": size })}
                  className={cn(
                    "min-h-10 flex-1 rounded-md border px-3 text-base transition-colors",
                    (settings?.text_size ?? "normal") === size
                      ? "border-ring bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-accent/60",
                  )}
                >
                  {size === "large" ? "A+ Large" : "A Normal"}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-start justify-between gap-4">
            <div className="flex flex-col">
              <span className="text-base font-medium">Chime on interesting clips</span>
              <span className="text-sm text-muted-foreground">
                A soft tone when a clip worth hearing arrives or plays. Off by default.
              </span>
            </div>
            <Switch
              checked={settings?.earcon_enabled ?? false}
              onCheckedChange={(checked) =>
                save.mutate({ earcon_enabled: checked ? "true" : "false" })
              }
              aria-label="Chime on interesting clips"
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="settings-watch-phrases" className="text-base">
              Always flag when heard
            </Label>
            <span className="text-sm text-muted-foreground">
              One phrase per line. Any clip whose transcript contains one is always marked
              worth hearing.
            </span>
            <textarea
              id="settings-watch-phrases"
              value={phrases}
              onChange={(event) => setPhrases(event.target.value)}
              rows={5}
              className="min-h-28 rounded-md border bg-background px-3 py-2 text-base"
              placeholder={"mayday\ngo around\ndiverting"}
            />
            <div className="flex justify-end">
              <Button
                type="button"
                variant="outline"
                onClick={saveWatchPhrases}
                disabled={save.isPending}
              >
                Save phrases
              </Button>
            </div>
          </div>
          <div className="flex justify-end">
            <Button type="submit" size="lg" disabled={save.isPending}>
              {save.isPending ? "Saving…" : "Done"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
