import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Camera, Crosshair, Loader2, SquareDashed } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { requestSnapshot } from "@/api/stubs";
import type { Camera as CameraType } from "@/types/surveillance";

// Internal canvas drawing resolution (16:9)
const CW = 960;
const CH = 540;
// Assumed actual camera frame resolution for coordinate scaling
const FRAME_W = 1920;
const FRAME_H = 1080;

interface ROI { x1: number; y1: number; x2: number; y2: number }
interface Rect { x: number; y: number; w: number; h: number }

interface ROICanvasProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  camera: CameraType;
  onConfirm: (roi: ROI) => void;
}

function roiToRect(roi: ROI): Rect {
  return {
    x: (roi.x1 / FRAME_W) * CW,
    y: (roi.y1 / FRAME_H) * CH,
    w: ((roi.x2 - roi.x1) / FRAME_W) * CW,
    h: ((roi.y2 - roi.y1) / FRAME_H) * CH,
  };
}

function rectToRoi(r: Rect): ROI {
  return {
    x1: Math.round((r.x / CW) * FRAME_W),
    y1: Math.round((r.y / CH) * FRAME_H),
    x2: Math.round(((r.x + r.w) / CW) * FRAME_W),
    y2: Math.round(((r.y + r.h) / CH) * FRAME_H),
  };
}

function isFullFrame(roi: ROI) {
  return roi.x1 === 0 && roi.y1 === 0 && roi.x2 === FRAME_W && roi.y2 === FRAME_H;
}

export function ROICanvas({ open, onOpenChange, camera, onConfirm }: ROICanvasProps) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [snapshotSrc, setSnapshotSrc] = useState<string | null>(null);
  const [loadingSnap, setLoadingSnap] = useState(false);
  const [drawing, setDrawing] = useState(false);
  const [startPt, setStartPt] = useState({ x: 0, y: 0 });
  const [rect, setRect] = useState<Rect | null>(null);

  // Initialise rect from existing ROI when the dialog opens
  useEffect(() => {
    if (!open) return;
    setSnapshotSrc(null);
    if (isFullFrame(camera.roi)) {
      setRect(null);
    } else {
      setRect(roiToRect(camera.roi));
    }
  }, [open, camera.roi]);

  // Redraw canvas overlay whenever rect changes
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, CW, CH);
    if (!rect || rect.w < 4 || rect.h < 4) return;

    // Semi-transparent fill
    ctx.fillStyle = "rgba(37, 99, 235, 0.18)";
    ctx.fillRect(rect.x, rect.y, rect.w, rect.h);

    // Dashed border
    ctx.strokeStyle = "#2563EB";
    ctx.lineWidth = 2;
    ctx.setLineDash([8, 4]);
    ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);

    // Corner handles
    ctx.setLineDash([]);
    ctx.fillStyle = "#2563EB";
    const corners: [number, number][] = [
      [rect.x, rect.y],
      [rect.x + rect.w, rect.y],
      [rect.x, rect.y + rect.h],
      [rect.x + rect.w, rect.y + rect.h],
    ];
    for (const [cx, cy] of corners) {
      ctx.fillRect(cx - 4, cy - 4, 8, 8);
    }
  }, [rect]);

  const getCanvasXY = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current!;
    const cr = canvas.getBoundingClientRect();
    // Scale mouse position from CSS display size → internal canvas resolution
    return {
      x: Math.max(0, Math.min(CW, ((e.clientX - cr.left) / cr.width) * CW)),
      y: Math.max(0, Math.min(CH, ((e.clientY - cr.top) / cr.height) * CH)),
    };
  }, []);

  const onMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const { x, y } = getCanvasXY(e);
    setDrawing(true);
    setStartPt({ x, y });
    setRect({ x, y, w: 0, h: 0 });
  };

  const onMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!drawing) return;
    const { x, y } = getCanvasXY(e);
    setRect({
      x: Math.min(startPt.x, x),
      y: Math.min(startPt.y, y),
      w: Math.abs(x - startPt.x),
      h: Math.abs(y - startPt.y),
    });
  };

  const onMouseUp = () => setDrawing(false);

  const loadSnapshot = async () => {
    setLoadingSnap(true);
    try {
      const r = await requestSnapshot(camera.id);
      setSnapshotSrc(`data:image/jpeg;base64,${r.image_base64}`);
    } catch {
      /* keep placeholder — stub returns 1x1 transparent PNG */
    } finally {
      setLoadingSnap(false);
    }
  };

  const handleConfirm = () => {
    if (!rect || rect.w < 4 || rect.h < 4) {
      onConfirm({ x1: 0, y1: 0, x2: FRAME_W, y2: FRAME_H });
    } else {
      onConfirm(rectToRoi(rect));
    }
    onOpenChange(false);
  };

  const handleClear = () => {
    setRect(null);
    onConfirm({ x1: 0, y1: 0, x2: FRAME_W, y2: FRAME_H });
    onOpenChange(false);
  };

  const roiLabel =
    rect && rect.w > 4 && rect.h > 4
      ? (() => {
          const r = rectToRoi(rect);
          return `x1=${r.x1}, y1=${r.y1}, x2=${r.x2}, y2=${r.y2}`;
        })()
      : `Full Frame (0, 0, ${FRAME_W}, ${FRAME_H})`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            {t("settings.roi")} — {camera.name}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <Button
              size="sm"
              variant="outline"
              onClick={loadSnapshot}
              disabled={loadingSnap}
            >
              {loadingSnap ? (
                <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
              ) : (
                <Camera className="h-4 w-4 mr-1.5" />
              )}
              {t("settings.roiLoadSnap")}
            </Button>
            <span className="text-xs text-muted-foreground">
              {t("settings.roiDrawHint")}
            </span>
          </div>

          {/* Canvas container — fixed 16:9 aspect ratio */}
          <div
            className="relative bg-zinc-900 rounded-md overflow-hidden select-none"
            style={{ aspectRatio: "16/9" }}
          >
            {snapshotSrc ? (
              <img
                src={snapshotSrc}
                className="absolute inset-0 w-full h-full object-cover"
                draggable={false}
                alt="Camera frame"
              />
            ) : (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 pointer-events-none">
                <Camera className="h-12 w-12 text-white/20" />
                <span className="text-xs text-white/40">
                  {t("settings.roiNoSnap")}
                </span>
              </div>
            )}

            {/* Transparent drawing canvas sits on top */}
            <canvas
              ref={canvasRef}
              width={CW}
              height={CH}
              className="absolute inset-0 w-full h-full cursor-crosshair"
              onMouseDown={onMouseDown}
              onMouseMove={onMouseMove}
              onMouseUp={onMouseUp}
              onMouseLeave={onMouseUp}
            />
          </div>

          {/* Live coordinate readout */}
          <div className="flex items-center gap-2">
            <Crosshair className="h-3.5 w-3.5 text-primary shrink-0" />
            <span className="text-xs font-mono text-muted-foreground">
              {t("settings.roiCurrent")}: {roiLabel}
            </span>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={handleClear}>
            <SquareDashed className="h-4 w-4 mr-1.5" />
            {t("settings.roiClear")}
          </Button>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={handleConfirm}>{t("common.confirm")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
