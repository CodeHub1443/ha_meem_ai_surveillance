import { useEffect, useRef } from "react";

export interface LogLine {
  text: string;
  ts?: string;
}

function severity(line: string): "error" | "warn" | "ok" {
  const u = line.toUpperCase();
  if (u.includes("ERROR") || u.includes("FAIL")) return "error";
  if (u.includes("WARN")) return "warn";
  return "ok";
}

export function TerminalLog({
  lines,
  showLineNumbers = false,
  autoScroll = true,
  height = 360,
}: {
  lines: string[];
  showLineNumbers?: boolean;
  autoScroll?: boolean;
  height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (autoScroll && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [lines, autoScroll]);

  return (
    <div
      ref={ref}
      className="rounded-md border bg-[#0B1220] text-[#7EE787] font-mono text-xs p-3 overflow-auto"
      style={{ height }}
    >
      {lines.length === 0 && <div className="text-muted-foreground italic">— empty —</div>}
      {lines.map((line, i) => {
        const sev = severity(line);
        const color = sev === "error" ? "text-red-400" : sev === "warn" ? "text-amber-300" : "text-[#7EE787]";
        return (
          <div key={i} className={`whitespace-pre-wrap break-all ${color}`}>
            {showLineNumbers && <span className="text-slate-500 mr-3 select-none">{String(i + 1).padStart(4, "0")}</span>}
            {line}
          </div>
        );
      })}
    </div>
  );
}
