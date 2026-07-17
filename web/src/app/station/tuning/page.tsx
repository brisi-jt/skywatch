import type { Metadata } from "next";

import { TuningBench } from "@/components/tuning/bench";

export const metadata: Metadata = {
  title: "Tuning bench",
};

export default function TuningPage() {
  return <TuningBench />;
}
