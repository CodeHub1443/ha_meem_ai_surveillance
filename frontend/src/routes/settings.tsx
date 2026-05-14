import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { AppShell } from "@/components/layout/AppShell";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { useSettings, DEFAULT_SETTINGS } from "@/context/SettingsContext";
import { saveSettings, testCamera, sendWhatsAppTest } from "@/api/stubs";
import { fetchHealth } from "@/api/events";
import type { AppSettings, Camera as CameraType } from "@/types/surveillance";
import { Lock, Eye, EyeOff, Plus, Trash2, X, Crop } from "lucide-react";
import { ROICanvas } from "@/components/shared/ROICanvas";

export const Route = createFileRoute("/settings")({ component: SettingsPage });

function SettingsPage() {
  const { t } = useTranslation();
  const { settings, setSettings, resetRecognition } = useSettings();
  const [draft, setDraft] = useState<AppSettings>(settings);
  useEffect(() => setDraft(settings), [settings]);

  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(settings), [draft, settings]);

  const save = async () => {
    setSettings(draft);
    try { await saveSettings(draft); } catch { /* ignore */ }
    toast.success(t("common.saved"));
  };

  return (
    <AppShell title={t("settings.title")}>
      {dirty && (
        <div className="mb-4 rounded-md bg-warning/10 border border-warning/30 px-4 py-2.5 flex items-center justify-between">
          <span className="text-sm text-warning font-medium">{t("common.unsaved")}</span>
          <Button size="sm" onClick={save}>{t("common.saveBackend")}</Button>
        </div>
      )}

      <Tabs defaultValue="cameras">
        <TabsList>
          <TabsTrigger value="cameras">{t("settings.tabs.cameras")}</TabsTrigger>
          <TabsTrigger value="recognition">{t("settings.tabs.recognition")}</TabsTrigger>
          <TabsTrigger value="whatsapp">{t("settings.tabs.whatsapp")}</TabsTrigger>
          <TabsTrigger value="system">{t("settings.tabs.system")}</TabsTrigger>
        </TabsList>

        <TabsContent value="cameras" className="mt-4">
          <CamerasTab draft={draft} setDraft={setDraft} />
        </TabsContent>
        <TabsContent value="recognition" className="mt-4">
          <RecognitionTab draft={draft} setDraft={setDraft} reset={resetRecognition} />
        </TabsContent>
        <TabsContent value="whatsapp" className="mt-4">
          <WhatsAppTab draft={draft} setDraft={setDraft} />
        </TabsContent>
        <TabsContent value="system" className="mt-4">
          <SystemTab draft={draft} setDraft={setDraft} />
        </TabsContent>
      </Tabs>

      {/* Reset to defaults handled in-tab */}
      <div className="hidden">{DEFAULT_SETTINGS.cameras.length}</div>
    </AppShell>
  );
}

/* ---------- Cameras ---------- */
function CamerasTab({ draft, setDraft }: { draft: AppSettings; setDraft: (s: AppSettings) => void }) {
  const { t } = useTranslation();
  const [delConfirm, setDelConfirm] = useState<string | null>(null);
  const [unlocked, setUnlocked] = useState<Record<string, boolean>>({});
  const [showRtsp, setShowRtsp] = useState<Record<string, boolean>>({});
  const [testing, setTesting] = useState<Record<string, "idle" | "ok" | "err" | "loading">>({});
  const [roiOpen, setRoiOpen] = useState<string | null>(null); // camera id whose ROI dialog is open

  const update = (id: string, patch: Partial<CameraType>) => {
    setDraft({ ...draft, cameras: draft.cameras.map((c) => (c.id === id ? { ...c, ...patch } : c)) });
  };

  const addCamera = () => {
    if (draft.cameras.length >= 8) { toast.warning(t("settings.maxCameras")); return; }
    const id = `camera_${String(draft.cameras.length + 1).padStart(2, "0")}`;
    setDraft({
      ...draft,
      cameras: [...draft.cameras, { id, name: "New Camera", rtsp_url: "", roi: { x1: 0, y1: 0, x2: 1920, y2: 1080 }, active: true }],
    });
    setUnlocked((u) => ({ ...u, [id]: true }));
  };

  const removeCamera = (id: string) => {
    setDraft({ ...draft, cameras: draft.cameras.filter((c) => c.id !== id) });
    setDelConfirm(null);
  };

  const test = async (id: string) => {
    setTesting((s) => ({ ...s, [id]: "loading" }));
    try {
      const r = await testCamera(id);
      setTesting((s) => ({ ...s, [id]: r.success ? "ok" : "err" }));
    } catch {
      setTesting((s) => ({ ...s, [id]: "err" }));
    }
  };

  return (
    <div className="space-y-4">
      {draft.cameras.map((c) => {
        const isUnlocked = unlocked[c.id] ?? false;
        return (
          <Card key={c.id} className="p-5 space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <Label className="text-xs">{t("settings.cameraName")}</Label>
                <Input value={c.name} onChange={(e) => update(c.id, { name: e.target.value })} placeholder="e.g., Front Entrance" />
              </div>
              <div>
                <Label className="text-xs">{t("settings.cameraId")}</Label>
                <div className="flex gap-2">
                  <Input
                    value={c.id} disabled={!isUnlocked}
                    onChange={(e) => {
                      const newId = e.target.value;
                      setDraft({ ...draft, cameras: draft.cameras.map((x) => x.id === c.id ? { ...x, id: newId } : x) });
                    }}
                  />
                  <Button type="button" size="icon" variant="outline" onClick={() => setUnlocked((u) => ({ ...u, [c.id]: !u[c.id] }))}>
                    <Lock className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </div>

            <div>
              <Label className="text-xs">{t("settings.rtspUrl")}</Label>
              <div className="flex gap-2">
                <Input
                  type={showRtsp[c.id] ? "text" : "password"}
                  value={c.rtsp_url} onChange={(e) => update(c.id, { rtsp_url: e.target.value })}
                  placeholder="rtsp://username:password@192.168.1.100:554/stream"
                />
                <Button type="button" size="icon" variant="outline" onClick={() => setShowRtsp((s) => ({ ...s, [c.id]: !s[c.id] }))}>
                  {showRtsp[c.id] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </Button>
              </div>
              <p className="text-[11px] text-muted-foreground mt-1">{t("settings.rtspHint")}</p>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <Label className="text-xs">{t("settings.roi")}</Label>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 text-xs"
                  onClick={() => setRoiOpen(c.id)}
                >
                  <Crop className="h-3.5 w-3.5 mr-1.5" />
                  {t("settings.roiDraw")}
                </Button>
              </div>
              {/* Manual numeric override — still editable for precision */}
              <div className="grid grid-cols-4 gap-2">
                {(["x1", "y1", "x2", "y2"] as const).map((k) => (
                  <div key={k}>
                    <span className="text-[10px] text-muted-foreground uppercase">{k}</span>
                    <Input
                      type="number"
                      min={0}
                      max={k === "x2" ? 7680 : 4320}
                      value={c.roi[k]}
                      onChange={(e) =>
                        update(c.id, { roi: { ...c.roi, [k]: Math.max(0, Number(e.target.value)) } })
                      }
                    />
                  </div>
                ))}
              </div>
              <p className="text-[11px] text-muted-foreground mt-1">{t("settings.roiHint")}</p>
            </div>

            <div className="flex items-center justify-between pt-2 border-t">
              <div className="flex items-center gap-2">
                <Switch checked={c.active} onCheckedChange={(v) => update(c.id, { active: v })} />
                <span className="text-sm">{c.active ? t("common.active") : t("common.inactive")}</span>
              </div>
              <div className="flex items-center gap-2">
                {testing[c.id] === "ok" && <Badge className="bg-success text-success-foreground">{t("common.connected")}</Badge>}
                {testing[c.id] === "err" && <Badge className="bg-danger text-danger-foreground">{t("common.error")}</Badge>}
                <Button size="sm" variant="outline" onClick={() => test(c.id)} disabled={testing[c.id] === "loading"}>{t("settings.testConnection")}</Button>
                <Button size="sm" variant="ghost" className="text-danger" onClick={() => setDelConfirm(c.id)}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </Card>
        );
      })}

      <Button variant="outline" onClick={addCamera}><Plus className="h-4 w-4 mr-2" />{t("settings.addCamera")}</Button>

      <ConfirmDialog
        open={!!delConfirm} onOpenChange={(o) => !o && setDelConfirm(null)}
        title={t("common.delete")} description={t("gallery.deleteWarn")} destructive
        onConfirm={() => delConfirm && removeCamera(delConfirm)}
      />

      {(() => {
        const cam = draft.cameras.find((c) => c.id === roiOpen);
        return cam ? (
          <ROICanvas
            open={!!roiOpen}
            onOpenChange={(o) => !o && setRoiOpen(null)}
            camera={cam}
            onConfirm={(roi) => update(cam.id, { roi })}
          />
        ) : null;
      })()}
    </div>
  );
}

/* ---------- Recognition ---------- */
function RecognitionTab({ draft, setDraft, reset }: { draft: AppSettings; setDraft: (s: AppSettings) => void; reset: () => void }) {
  const { t } = useTranslation();
  const r = draft.recognition;
  const set = (patch: Partial<typeof r>) => setDraft({ ...draft, recognition: { ...r, ...patch } });

  return (
    <Card className="p-6 space-y-6">
      <SliderRow
        label={t("settings.rec.similarity")} hint={t("settings.rec.similarityHint")}
        min={0.4} max={0.9} step={0.01} value={r.similarity_threshold}
        onChange={(v) => set({ similarity_threshold: v })}
        warning={r.similarity_threshold < 0.5 ? t("settings.rec.lowWarn") : undefined}
      />
      <SliderRow label={t("settings.rec.minFace")} hint={t("settings.rec.minFaceHint")}
        min={40} max={200} step={10} value={r.min_face_size} onChange={(v) => set({ min_face_size: v })} />
      <SliderRow label={t("settings.rec.margin")} hint={t("settings.rec.marginHint")}
        min={0} max={0.2} step={0.01} value={r.match_margin} onChange={(v) => set({ match_margin: v })} />
      <SliderRow label={t("settings.rec.cooldown")} hint={t("settings.rec.cooldownHint")}
        min={5} max={300} step={5} value={r.identity_cooldown} onChange={(v) => set({ identity_cooldown: v })} />

      <div className="flex items-center justify-between">
        <div>
          <Label className="text-sm">{t("settings.rec.adaptive")}</Label>
          <p className="text-xs text-muted-foreground">{t("settings.rec.adaptiveHint")}</p>
        </div>
        <Switch checked={r.adaptive_blur} onCheckedChange={(v) => set({ adaptive_blur: v })} />
      </div>

      <SliderRow label={t("settings.rec.blur")} hint={t("settings.rec.blurHint")}
        min={5} max={100} step={5} value={r.blur_threshold} onChange={(v) => set({ blur_threshold: v })}
        disabled={r.adaptive_blur} />

      <SliderRow label={t("settings.rec.decision")} hint={t("settings.rec.decisionHint")}
        min={0.1} max={2} step={0.1} value={r.min_decision_time} onChange={(v) => set({ min_decision_time: v })} />

      <SliderRow label={t("settings.rec.decay")} hint={t("settings.rec.decayHint")}
        min={0.8} max={1} step={0.01} value={r.recency_decay} onChange={(v) => set({ recency_decay: v })} />

      <div className="pt-4 border-t">
        <Button variant="outline" onClick={reset}>{t("settings.rec.resetDefaults")}</Button>
      </div>
    </Card>
  );
}

function SliderRow({ label, hint, min, max, step, value, onChange, warning, disabled }: {
  label: string; hint: string; min: number; max: number; step: number; value: number; onChange: (v: number) => void; warning?: string; disabled?: boolean;
}) {
  return (
    <div className={disabled ? "opacity-50 pointer-events-none" : ""}>
      <div className="flex items-center justify-between mb-1.5">
        <Label className="text-sm">{label}</Label>
        <span className="text-sm font-mono tabular-nums w-16 text-right">{value}</span>
      </div>
      <Slider min={min} max={max} step={step} value={[value]} onValueChange={(v) => onChange(v[0])} />
      <p className="text-xs text-muted-foreground mt-1.5">{hint}</p>
      {warning && <p className="text-xs text-warning mt-1">⚠ {warning}</p>}
    </div>
  );
}

/* ---------- WhatsApp ---------- */
function WhatsAppTab({ draft, setDraft }: { draft: AppSettings; setDraft: (s: AppSettings) => void }) {
  const { t } = useTranslation();
  const w = draft.whatsapp;
  const set = (patch: Partial<typeof w>) => setDraft({ ...draft, whatsapp: { ...w, ...patch } });
  const [showToken, setShowToken] = useState(false);
  const [recipient, setRecipient] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);

  const addRecipient = () => {
    if (!recipient || w.recipients.length >= 5 || w.recipients.includes(recipient)) return;
    set({ recipients: [...w.recipients, recipient] });
    setRecipient("");
  };

  const sendTest = async () => {
    setTesting(true); setTestResult(null);
    try {
      const r = await sendWhatsAppTest();
      setTestResult(r.success ? "ok" : "err");
      toast[r.success ? "success" : "error"](r.message);
    } finally { setTesting(false); }
  };

  const configured = !!(w.phone_number_id && w.access_token);

  return (
    <Card className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <Label className="text-sm">{t("settings.wa.enable")}</Label>
        </div>
        <div className="flex items-center gap-2">
          <Badge className={configured ? "bg-success text-success-foreground" : "bg-muted text-muted-foreground"}>
            {configured ? t("settings.wa.configured") : t("settings.wa.notConfigured")}
          </Badge>
          <Switch checked={w.enabled} onCheckedChange={(v) => set({ enabled: v })} />
        </div>
      </div>

      <div>
        <Label className="text-xs">{t("settings.wa.phoneId")}</Label>
        <Input value={w.phone_number_id} onChange={(e) => set({ phone_number_id: e.target.value })} placeholder="1234567890123456" />
        <p className="text-[11px] text-muted-foreground mt-1">{t("settings.wa.phoneIdHint")}</p>
      </div>

      <div>
        <Label className="text-xs">{t("settings.wa.token")}</Label>
        <div className="flex gap-2">
          <Input type={showToken ? "text" : "password"} value={w.access_token} onChange={(e) => set({ access_token: e.target.value })} placeholder="EAAxxxxxxxxxxxxx..." />
          <Button type="button" variant="outline" size="icon" onClick={() => setShowToken((s) => !s)}>
            {showToken ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </Button>
        </div>
        <p className="text-[11px] text-muted-foreground mt-1">{t("settings.wa.tokenHint")}</p>
      </div>

      <div>
        <Label className="text-xs">{t("settings.wa.version")}</Label>
        <Input value={w.api_version} onChange={(e) => set({ api_version: e.target.value })} placeholder="v19.0" />
        <p className="text-[11px] text-muted-foreground mt-1">{t("settings.wa.versionHint")}</p>
      </div>

      <div>
        <Label className="text-xs">{t("settings.wa.recipients")}</Label>
        <div className="flex gap-2">
          <Input value={recipient} onChange={(e) => setRecipient(e.target.value)} placeholder="+8801XXXXXXXXX"
            onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addRecipient())} />
          <Button type="button" variant="outline" onClick={addRecipient}>{t("common.add")}</Button>
        </div>
        <div className="flex flex-wrap gap-2 mt-2">
          {w.recipients.map((r) => (
            <Badge key={r} variant="outline" className="gap-1">
              {r}
              <button onClick={() => set({ recipients: w.recipients.filter((x) => x !== r) })}>
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
        <p className="text-[11px] text-muted-foreground mt-1">{t("settings.wa.recipientsHint")}</p>
      </div>

      <div>
        <Label className="text-xs">{t("settings.wa.template")}</Label>
        <Textarea rows={5} value={w.template} onChange={(e) => set({ template: e.target.value })} className="font-mono text-xs" />
        <p className="text-[11px] text-muted-foreground mt-1">
          {t("settings.wa.templateHint", { vars: "{camera_id}, {timestamp}, {score}, {identity}" })}
        </p>
      </div>

      <div className="flex items-center justify-between">
        <div>
          <Label className="text-sm">{t("settings.wa.includeSnap")}</Label>
          <p className="text-xs text-muted-foreground">{t("settings.wa.includeSnapHint")}</p>
        </div>
        <Switch checked={w.include_snapshot} onCheckedChange={(v) => set({ include_snapshot: v })} />
      </div>

      <div className="pt-4 border-t flex items-center gap-3">
        <Button onClick={sendTest} disabled={!configured || testing}>{t("settings.wa.sendTest")}</Button>
        {testResult === "ok" && <span className="text-xs text-success">✓ Sent</span>}
        {testResult === "err" && <span className="text-xs text-danger">✗ Failed</span>}
      </div>
    </Card>
  );
}

/* ---------- System ---------- */
function SystemTab({ draft, setDraft }: { draft: AppSettings; setDraft: (s: AppSettings) => void }) {
  const { t } = useTranslation();
  const s = draft.system;
  const set = (patch: Partial<typeof s>) => setDraft({ ...draft, system: { ...s, ...patch } });
  const [showModels, setShowModels] = useState(false);
  const [testStatus, setTestStatus] = useState<"idle" | "ok" | "err" | "loading">("idle");

  const testApi = async () => {
    setTestStatus("loading");
    try { await fetchHealth(); setTestStatus("ok"); }
    catch { setTestStatus("err"); }
  };

  return (
    <Card className="p-6 space-y-5">
      <div>
        <Label className="text-xs">{t("settings.sys.apiBase")}</Label>
        <div className="flex gap-2">
          <Input value={s.api_base_url} onChange={(e) => set({ api_base_url: e.target.value })} />
          <Button variant="outline" onClick={testApi} disabled={testStatus === "loading"}>{t("settings.testConnection")}</Button>
        </div>
        {testStatus === "ok" && <span className="text-xs text-success mt-1 inline-block">✓ {t("common.connected")}</span>}
        {testStatus === "err" && <span className="text-xs text-danger mt-1 inline-block">✗ {t("common.disconnected")}</span>}
      </div>

      <div>
        <Label className="text-xs">{t("settings.sys.device")}</Label>
        <Select value={s.device} onValueChange={(v) => set({ device: v as "CUDA" | "CPU" })}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="CUDA">CUDA</SelectItem>
            <SelectItem value="CPU">CPU</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-[11px] text-muted-foreground mt-1">{t("settings.sys.deviceHint")}</p>
      </div>

      <div className="flex items-center justify-between">
        <div>
          <Label className="text-sm">{t("settings.sys.tensorrt")}</Label>
          <p className="text-xs text-muted-foreground">{t("settings.sys.tensorrtHint")}</p>
        </div>
        <Switch checked={s.tensorrt} onCheckedChange={(v) => set({ tensorrt: v })} />
      </div>

      {s.tensorrt && (
        <div>
          <Label className="text-xs">{t("settings.sys.trtCache")}</Label>
          <Input value={s.trt_cache} onChange={(e) => set({ trt_cache: e.target.value })} />
        </div>
      )}

      <div>
        <Label className="text-xs">{t("settings.sys.logLevel")}</Label>
        <Select value={s.log_level} onValueChange={(v) => set({ log_level: v as typeof s.log_level })}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            {["DEBUG", "INFO", "WARNING", "ERROR"].map((x) => <SelectItem key={x} value={x}>{x}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      <div>
        <Label className="text-xs">{t("settings.sys.retention")}</Label>
        <Input type="number" value={s.snapshot_retention_days} onChange={(e) => set({ snapshot_retention_days: Number(e.target.value) })} />
        <p className="text-[11px] text-muted-foreground mt-1">{t("settings.sys.retentionHint")}</p>
      </div>

      <div className="border-t pt-4">
        <button onClick={() => setShowModels(!showModels)} className="text-sm font-medium text-primary">
          {t("settings.sys.models")} {showModels ? "▾" : "▸"}
        </button>
        {showModels && (
          <div className="mt-3 space-y-2 text-xs font-mono bg-muted p-3 rounded">
            <div>SCRFD: <span className="text-muted-foreground">models/exported/scrfd_10g_bnkps.onnx</span></div>
            <div>AdaFace: <span className="text-muted-foreground">models/exported/adaface.onnx</span></div>
            <div>Gallery: <span className="text-muted-foreground">data/gallery_embeddings.npy</span></div>
            <p className="text-[11px] text-muted-foreground mt-2 font-sans not-italic">{t("settings.sys.modelsHint")}</p>
          </div>
        )}
      </div>
    </Card>
  );
}
