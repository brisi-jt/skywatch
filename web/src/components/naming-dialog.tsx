"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSaveSettings } from "@/lib/api/hooks";

const SKIP_KEY = "skywatch.naming-skipped";

/**
 * The first interaction of the gift: christening the station. Appears when
 * the station has no name yet; skipping defers quietly for the session and
 * the name stays editable in Settings.
 */
export function NamingDialog({
  stationName,
}: {
  /** undefined = status not loaded yet; null = unnamed. */
  stationName: string | null | undefined;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const save = useSaveSettings();

  useEffect(() => {
    if (stationName === null && sessionStorage.getItem(SKIP_KEY) !== "1") {
      setOpen(true);
    }
  }, [stationName]);

  const skip = () => {
    sessionStorage.setItem(SKIP_KEY, "1");
    setOpen(false);
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    save.mutate(
      { station_name: trimmed },
      { onSuccess: () => setOpen(false) },
    );
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? setOpen(true) : skip())}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">Name your station</DialogTitle>
          <DialogDescription className="text-base">
            This listening post is yours. Give it a name and the dashboard will fly your colours —
            you can change it any time in settings.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="station-name" className="text-base">
              Station name
            </Label>
            <Input
              id="station-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="My Airband Station"
              className="h-11 text-base"
              autoFocus
            />
          </div>
          {save.isError && (
            <p className="text-sm text-health-bad">That name could not be saved — try another.</p>
          )}
          <div className="flex items-center justify-between gap-3">
            <button
              type="button"
              onClick={skip}
              className="min-h-10 text-base text-muted-foreground underline-offset-4 hover:underline"
            >
              skip for now
            </button>
            <Button type="submit" size="lg" disabled={!name.trim() || save.isPending}>
              {save.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
