import { useState, useEffect } from "react";
import { format } from "date-fns";

/** Returns today's date as "yyyy-MM-dd". Re-triggers at midnight automatically. */
export function useToday(): string {
  const [today, setToday] = useState(() => format(new Date(), "yyyy-MM-dd"));

  useEffect(() => {
    let timeout: ReturnType<typeof setTimeout>;

    const scheduleNextMidnight = () => {
      const now = new Date();
      const midnight = new Date(now);
      midnight.setHours(24, 0, 0, 0);
      const msUntilMidnight = midnight.getTime() - now.getTime();

      timeout = setTimeout(() => {
        setToday(format(new Date(), "yyyy-MM-dd"));
        scheduleNextMidnight();
      }, msUntilMidnight);
    };

    scheduleNextMidnight();
    return () => clearTimeout(timeout);
  }, []);

  return today;
}
