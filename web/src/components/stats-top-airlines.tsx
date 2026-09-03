import { GaugeBar } from "@/components/gauge-bar";
import type { AirlineCount } from "@/lib/api/client";
import { airlineFractions } from "@/lib/stats-chart";

export function StatsTopAirlines({ airlines }: { airlines: AirlineCount[] }) {
  if (airlines.length === 0) {
    return (
      <p className="mt-3 text-base text-muted-foreground">
        No airline has been identified from the traffic overhead yet.
      </p>
    );
  }
  return (
    <div className="mt-3 flex flex-col gap-3">
      {airlineFractions(airlines).map((a) => (
        <GaugeBar
          key={a.airline_name}
          label={a.airline_name}
          detail={`${a.count} ${a.count === 1 ? "clip" : "clips"}`}
          fraction={a.fraction}
        />
      ))}
    </div>
  );
}
