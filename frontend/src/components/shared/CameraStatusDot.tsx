export function CameraStatusDot({ active }: { active: boolean }) {
  if (active) {
    return (
      <span className="relative inline-flex h-2.5 w-2.5">
        <span className="absolute inset-0 rounded-full bg-success pulse-dot" />
      </span>
    );
  }
  return <span className="inline-block h-2.5 w-2.5 rounded-full bg-muted-foreground/40" />;
}
