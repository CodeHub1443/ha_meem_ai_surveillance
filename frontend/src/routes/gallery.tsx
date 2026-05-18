import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { format } from "date-fns";
import { toast } from "sonner";
import { AppShell } from "@/components/layout/AppShell";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import {
  fetchPersons, createPerson, deletePerson, fetchPersonSamples, buildGallery, fetchBuildStatus,
} from "@/api/persons";
import { SnapshotModal } from "@/components/shared/SnapshotModal";
import { API_BASE_URL } from "@/api/config";
import { Hammer, Trash2, UserPlus, Users, Upload, Images, ShieldCheck, Loader2 } from "lucide-react";
import type { Person } from "@/types/surveillance";

export const Route = createFileRoute("/gallery")({ component: GalleryPage });

function GalleryPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [buildOpen, setBuildOpen] = useState(false);
  const [confirmDel, setConfirmDel] = useState<string | null>(null);
  const [samplesFor, setSamplesFor] = useState<Person | null>(null);
  const [building, setBuilding] = useState(false);
  const [progress, setProgress] = useState(0);
  const [lastBuilt, setLastBuilt] = useState<string | null>(null);
  const [zoomImg, setZoomImg] = useState<string | null>(null);

  const pendingQ  = useQuery({ queryKey: ["persons", "pending"],  queryFn: () => fetchPersons("pending"),  staleTime: 60_000 });
  const enrolledQ = useQuery({ queryKey: ["persons", "enrolled"], queryFn: () => fetchPersons("enrolled"), staleTime: 60_000 });

  const delMut = useMutation({
    mutationFn: deletePerson,
    onSuccess: () => {
      toast.success(t("common.deleted"));
      void qc.invalidateQueries({ queryKey: ["persons"] });
    },
  });

  // Poll build status while building
  useEffect(() => {
    if (!building) return;
    const id = setInterval(async () => {
      try {
        const s = await fetchBuildStatus();
        setProgress((p) => Math.min(p + 6, 95));
        if (!s.running) {
          clearInterval(id);
          setBuilding(false);
          setProgress(100);
          setLastBuilt(new Date().toISOString());
          void qc.invalidateQueries({ queryKey: ["persons"] });
          if (s.last_result?.success) {
            toast.success(t("gallery.buildSuccess", { n: s.last_result.persons_enrolled ?? 0 }));
          } else {
            toast.error(s.last_result?.error ?? "Build failed");
          }
          setTimeout(() => setProgress(0), 1500);
        }
      } catch {
        // API temporarily unreachable mid-build — keep polling
      }
    }, 1500);
    return () => clearInterval(id);
  }, [building, qc, t]);

  const startBuild = async () => {
    setBuildOpen(false);
    setBuilding(true);
    setProgress(0);
    try { await buildGallery(); } catch (e) {
      setBuilding(false);
      toast.error(String(e));
    }
  };

  const filterFn = (p: Person) => p.name.toLowerCase().includes(search.toLowerCase());
  const pending  = (pendingQ.data  ?? []).filter(filterFn);
  const enrolled = (enrolledQ.data ?? []).filter(filterFn);

  return (
    <AppShell title={t("gallery.title")}>
      {/* Toolbar */}
      <Card className="p-4 mb-4 flex items-center gap-3 flex-wrap">
        <Input placeholder={t("common.search")} value={search} onChange={(e) => setSearch(e.target.value)} className="max-w-xs" />
        <Button variant="outline" onClick={() => setAddOpen(true)}>
          <UserPlus className="h-4 w-4 mr-2" />{t("gallery.addPerson")}
        </Button>
        <Button onClick={() => setBuildOpen(true)} disabled={building}>
          <Hammer className="h-4 w-4 mr-2" />{t("gallery.build")}
        </Button>
        <div className="ml-auto text-xs text-muted-foreground">
          {lastBuilt
            ? `${t("gallery.lastBuilt")}: ${format(new Date(lastBuilt), "yyyy-MM-dd HH:mm")}`
            : t("gallery.notBuilt")}
        </div>
      </Card>

      {/* Build progress */}
      {building && (
        <Card className="p-4 mb-4">
          <div className="flex items-center gap-2 mb-2">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground shrink-0" />
            <span className="text-sm font-medium">{t("gallery.building")}</span>
          </div>
          <Progress value={progress} />
          <p className="text-[11px] text-muted-foreground mt-2">{t("gallery.buildStepsHint")}</p>
        </Card>
      )}

      {/* Two-tab view */}
      <Tabs defaultValue="directory">
        <TabsList>
          <TabsTrigger value="directory">
            {t("gallery.personDirectory")}
            {(pendingQ.data?.length ?? 0) > 0 && (
              <Badge variant="secondary" className="ml-2 text-[10px] h-4 px-1.5">{pendingQ.data!.length}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="enrolled">{t("gallery.enrolledPeople")}</TabsTrigger>
        </TabsList>

        {/* ── Pending / Person Directory ── */}
        <TabsContent value="directory" className="mt-4">
          {pendingQ.isLoading ? (
            <PersonGridSkeleton />
          ) : pending.length === 0 ? (
            <Card className="p-12 text-center">
              <Users className="h-12 w-12 mx-auto text-muted-foreground/40 mb-3" />
              <p className="text-sm text-muted-foreground">
                {t("gallery.noPendingPersons")}
              </p>
            </Card>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {pending.map((p) => (
                <PersonCard key={p.id} person={p} onViewSamples={() => setSamplesFor(p)} onDelete={() => setConfirmDel(p.id)} onZoom={setZoomImg} />
              ))}
            </div>
          )}
        </TabsContent>

        {/* ── Enrolled People ── */}
        <TabsContent value="enrolled" className="mt-4">
          {enrolledQ.isLoading ? (
            <PersonGridSkeleton />
          ) : enrolled.length === 0 ? (
            <Card className="p-12 text-center">
              <Users className="h-12 w-12 mx-auto text-muted-foreground/40 mb-3" />
              <p className="text-sm text-muted-foreground">{t("gallery.noPersons")}</p>
            </Card>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {enrolled.map((p) => (
                <PersonCard key={p.id} person={p} onViewSamples={() => setSamplesFor(p)} onDelete={() => setConfirmDel(p.id)} onZoom={setZoomImg} enrolled />
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* Dialogs */}
      <AddPersonDialog open={addOpen} onOpenChange={setAddOpen} />

      <ViewSamplesDialog person={samplesFor} open={!!samplesFor} onOpenChange={(o) => !o && setSamplesFor(null)} onZoom={setZoomImg} />
      <SnapshotModal open={!!zoomImg} onOpenChange={(o) => !o && setZoomImg(null)} src={zoomImg} />

      <ConfirmDialog
        open={buildOpen} onOpenChange={setBuildOpen}
        title={t("gallery.build")} description={t("gallery.buildWarn")}
        onConfirm={startBuild}
      />

      <ConfirmDialog
        open={!!confirmDel} onOpenChange={(o) => !o && setConfirmDel(null)}
        title={t("gallery.deletePerson")} description={t("gallery.deleteWarn")} destructive
        onConfirm={() => { if (confirmDel) delMut.mutate(confirmDel); setConfirmDel(null); }}
      />
    </AppShell>
  );
}

/* ── Person card ── */
function PersonCard({ person, onViewSamples, onDelete, onZoom, enrolled = false }: {
  person: Person; onViewSamples: () => void; onDelete: () => void; onZoom: (url: string) => void; enrolled?: boolean;
}) {
  const { t } = useTranslation();
  const thumbSrc = person.thumbnail_url
    ? person.thumbnail_url.startsWith("http") ? person.thumbnail_url : `${API_BASE_URL}/${person.thumbnail_url}`
    : null;

  return (
    <Card className="p-5 text-center">
      {thumbSrc ? (
        <button
          className="h-20 w-20 rounded-full overflow-hidden mx-auto mb-3 border-2 border-border block hover:ring-2 hover:ring-primary transition-all"
          onClick={() => onZoom(person.thumbnail_url!)}
          aria-label={t("gallery.viewSamples")}
        >
          <img src={thumbSrc} className="h-full w-full object-cover" alt={person.name} />
        </button>
      ) : (
        <div className="h-20 w-20 rounded-full bg-primary/10 mx-auto mb-3 flex items-center justify-center text-lg font-semibold text-primary border-2 border-border">
          {person.name.split(" ").map((s) => s[0]).join("").slice(0, 2).toUpperCase()}
        </div>
      )}
      <h3 className="font-medium text-sm text-foreground">{person.name}</h3>
      {person.employee_id && (
        <p className="text-[11px] text-muted-foreground mt-0.5">{person.employee_id}</p>
      )}
      {person.designation && (
        <p className="text-[11px] text-muted-foreground">{person.designation}</p>
      )}
      {person.working_area && (
        <p className="text-[11px] text-muted-foreground">{person.working_area}</p>
      )}
      <p className="text-xs text-muted-foreground mt-1">{person.sample_count} {t("gallery.samples")}</p>
      {person.avg_accuracy != null && (
        <p className="text-xs text-muted-foreground">{t("gallery.avg")} <span className="font-medium text-foreground">{person.avg_accuracy}%</span></p>
      )}
      {enrolled ? (
        <div className="flex items-center justify-center gap-1 mt-2">
          <ShieldCheck className="h-3.5 w-3.5 text-success" />
          <span className="text-xs text-success font-medium">{t("events.authorized")}</span>
        </div>
      ) : (
        <Badge variant="outline" className="mt-2 text-[10px]">{t("gallery.pending")}</Badge>
      )}
      <div className="flex gap-2 mt-3 justify-center">
        <Button size="sm" variant="ghost" onClick={onViewSamples}>
          <Images className="h-3.5 w-3.5 mr-1" />{t("gallery.viewSamples")}
        </Button>
        <Button size="sm" variant="ghost" className="text-danger hover:text-danger" onClick={onDelete}>
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
    </Card>
  );
}

/* ── View samples dialog ── */
function ViewSamplesDialog({ person, open, onOpenChange, onZoom }: {
  person: Person | null; open: boolean; onOpenChange: (v: boolean) => void; onZoom: (url: string) => void;
}) {
  const { t } = useTranslation();
  const samplesQ = useQuery({
    queryKey: ["person-samples", person?.id],
    queryFn: () => fetchPersonSamples(person!.id),
    enabled: open && !!person,
    staleTime: 300_000,
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{person?.name} — {t("gallery.viewSamples")}</DialogTitle>
        </DialogHeader>
        {samplesQ.isLoading ? (
          <div className="grid grid-cols-3 gap-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="aspect-square bg-muted animate-pulse rounded-md" />
            ))}
          </div>
        ) : samplesQ.isError ? (
          <div className="text-center py-10 space-y-2">
            <p className="text-sm text-danger">{t("common.error")}</p>
            <Button size="sm" variant="outline" onClick={() => samplesQ.refetch()}>{t("common.retry")}</Button>
          </div>
        ) : samplesQ.data?.length ? (
          <div className="grid grid-cols-3 sm:grid-cols-4 gap-3 max-h-[60vh] overflow-y-auto pr-1">
            {samplesQ.data.map((url, i) => (
              <button
                key={i}
                className="aspect-square overflow-hidden rounded-md border bg-muted hover:ring-2 hover:ring-primary transition-all"
                onClick={() => onZoom(url)}
              >
                <img
                  src={url.startsWith("http") ? url : `${API_BASE_URL}/${url}`}
                  className="w-full h-full object-cover"
                  alt={`Sample ${i + 1}`}
                />
              </button>
            ))}
          </div>
        ) : (
          <div className="text-center py-10 text-sm text-muted-foreground">{t("gallery.noSamples")}</div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>{t("common.close")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ── Add person dialog ── */
function AddPersonDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [employeeId, setEmployeeId] = useState("");
  const [designation, setDesignation] = useState("");
  const [workingArea, setWorkingArea] = useState("");
  const [files, setFiles] = useState<File[]>([]);

  const reset = () => { setName(""); setEmployeeId(""); setDesignation(""); setWorkingArea(""); setFiles([]); };

  const mut = useMutation({
    mutationFn: () => createPerson({ name, employee_id: employeeId || undefined, designation: designation || undefined, working_area: workingArea || undefined, images: files }),
    onSuccess: () => {
      toast.success(t("common.saved"));
      void qc.invalidateQueries({ queryKey: ["persons"] });
      onOpenChange(false);
      reset();
    },
    onError: (e) => toast.error(String(e)),
  });

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) reset(); onOpenChange(v); }}>
      <DialogContent className="max-w-md">
        <DialogHeader><DialogTitle>{t("gallery.addPerson")}</DialogTitle></DialogHeader>
        <div className="space-y-4">
          <div>
            <Label className="text-xs font-medium mb-1 block">{t("gallery.fullName")} *</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Full name" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs font-medium mb-1 block">{t("gallery.employeeId")}</Label>
              <Input value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} placeholder="EMP-001" />
            </div>
            <div>
              <Label className="text-xs font-medium mb-1 block">{t("gallery.designation")}</Label>
              <Input value={designation} onChange={(e) => setDesignation(e.target.value)} placeholder="Operator" />
            </div>
          </div>
          <div>
            <Label className="text-xs font-medium mb-1 block">{t("gallery.workingArea")}</Label>
            <Input value={workingArea} onChange={(e) => setWorkingArea(e.target.value)} placeholder="Gate A / Zone 1" />
          </div>
          <div>
            <Label className="text-xs font-medium mb-1 block">{t("gallery.facePhotos")}</Label>
            <label className="border-2 border-dashed rounded-md p-6 flex flex-col items-center justify-center cursor-pointer hover:bg-muted/30">
              <Upload className="h-6 w-6 text-muted-foreground mb-2" />
              <span className="text-xs text-muted-foreground">{t("gallery.uploadTypes")}</span>
              <input type="file" accept="image/*" multiple className="hidden"
                onChange={(e) => setFiles(Array.from(e.target.files || []))} />
            </label>
            {files.length > 0 && (
              <p className="text-xs text-muted-foreground mt-2">{t("gallery.filesSelected", { n: files.length })}</p>
            )}
            <p className="text-[11px] text-muted-foreground mt-2">{t("gallery.uploadHint")}</p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => { reset(); onOpenChange(false); }}>{t("common.cancel")}</Button>
          <Button onClick={() => mut.mutate()} disabled={!name.trim() || mut.isPending}>{t("gallery.savePerson")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PersonGridSkeleton() {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="h-44 bg-card rounded-lg animate-pulse border" />
      ))}
    </div>
  );
}
