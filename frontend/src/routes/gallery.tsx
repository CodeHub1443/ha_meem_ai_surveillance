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
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import {
  fetchPersons,
  fetchPersonSamples,
  createPerson,
  deletePerson,
  buildGallery,
  fetchBuildStatus,
} from "@/api/stubs";
import { API_BASE_URL } from "@/api/config";
import { Hammer, Trash2, UserPlus, Users, Upload, Images } from "lucide-react";
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
  const [progressMsg, setProgressMsg] = useState("");
  const [lastBuilt, setLastBuilt] = useState<string | null>(null);

  const persons = useQuery({ queryKey: ["persons"], queryFn: fetchPersons });

  const delMut = useMutation({
    mutationFn: deletePerson,
    onSuccess: () => {
      toast.success(t("common.saved"));
      void qc.invalidateQueries({ queryKey: ["persons"] });
    },
  });

  // Poll build status while a build is in progress
  useEffect(() => {
    if (!building) return;
    const id = setInterval(async () => {
      const s = await fetchBuildStatus();
      setProgress(s.progress);
      setProgressMsg(s.message);
      if (s.status === "done") {
        clearInterval(id);
        setBuilding(false);
        setLastBuilt(new Date().toISOString());
        void qc.invalidateQueries({ queryKey: ["persons"] });
        toast.success(t("gallery.buildSuccess", { n: persons.data?.length || 0 }));
      }
    }, 1500);
    return () => clearInterval(id);
  }, [building, persons.data, t, qc]);

  const startBuild = async () => {
    setBuildOpen(false);
    setBuilding(true);
    setProgress(0);
    setProgressMsg("");
    await buildGallery();
  };

  const filtered = (persons.data || []).filter((p) =>
    p.name.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <AppShell title={t("gallery.title")}>
      {/* Toolbar */}
      <Card className="p-4 mb-4 flex items-center gap-3 flex-wrap">
        <Input
          placeholder={t("common.search")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-xs"
        />
        <Button variant="outline" onClick={() => setAddOpen(true)}>
          <UserPlus className="h-4 w-4 mr-2" />
          {t("gallery.addPerson")}
        </Button>
        <Button onClick={() => setBuildOpen(true)} disabled={building}>
          <Hammer className="h-4 w-4 mr-2" />
          {t("gallery.build")}
        </Button>
        <div className="ml-auto text-xs text-muted-foreground">
          {lastBuilt
            ? `${t("gallery.lastBuilt")}: ${format(new Date(lastBuilt), "yyyy-MM-dd HH:mm")}`
            : t("gallery.notBuilt")}
        </div>
      </Card>

      {/* Two-phase build progress */}
      {building && (
        <Card className="p-4 mb-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">
              {progressMsg || t("common.loading")}
            </span>
            <span className="text-xs text-muted-foreground">{progress}%</span>
          </div>
          <Progress value={progress} />
          <p className="text-[11px] text-muted-foreground mt-2">
            {t("gallery.buildStepsHint")}
          </p>
        </Card>
      )}

      {/* Person grid */}
      {persons.isLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-44 bg-card rounded-lg animate-pulse border" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <Card className="p-12 text-center">
          <Users className="h-12 w-12 mx-auto text-muted-foreground/40 mb-3" />
          <p className="text-sm text-muted-foreground">{t("gallery.noPersons")}</p>
        </Card>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {filtered.map((p) => (
            <PersonCard
              key={p.id}
              person={p}
              onViewSamples={() => setSamplesFor(p)}
              onDelete={() => setConfirmDel(p.id)}
            />
          ))}
        </div>
      )}

      {/* Dialogs */}
      <AddPersonDialog open={addOpen} onOpenChange={setAddOpen} />

      <ViewSamplesDialog
        person={samplesFor}
        open={!!samplesFor}
        onOpenChange={(o) => !o && setSamplesFor(null)}
      />

      <ConfirmDialog
        open={buildOpen}
        onOpenChange={setBuildOpen}
        title={t("gallery.build")}
        description={t("gallery.buildWarn")}
        onConfirm={startBuild}
      />

      <ConfirmDialog
        open={!!confirmDel}
        onOpenChange={(o) => !o && setConfirmDel(null)}
        title={t("gallery.deletePerson")}
        description={t("gallery.deleteWarn")}
        destructive
        onConfirm={() => {
          if (confirmDel) delMut.mutate(confirmDel);
          setConfirmDel(null);
        }}
      />
    </AppShell>
  );
}

/* ---------- Person card ---------- */
function PersonCard({
  person,
  onViewSamples,
  onDelete,
}: {
  person: Person;
  onViewSamples: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const thumbSrc =
    person.thumbnail_url
      ? person.thumbnail_url.startsWith("http")
        ? person.thumbnail_url
        : `${API_BASE_URL}/${person.thumbnail_url}`
      : null;

  return (
    <Card className="p-5 text-center">
      {thumbSrc ? (
        <img
          src={thumbSrc}
          className="h-20 w-20 rounded-full object-cover mx-auto mb-3 border-2 border-border"
          alt={person.name}
        />
      ) : (
        <div className="h-20 w-20 rounded-full bg-primary/10 mx-auto mb-3 flex items-center justify-center text-lg font-semibold text-primary border-2 border-border">
          {person.name
            .split(" ")
            .map((s) => s[0])
            .join("")
            .slice(0, 2)
            .toUpperCase()}
        </div>
      )}
      <h3 className="font-medium text-sm text-foreground">{person.name}</h3>
      <p className="text-xs text-muted-foreground mt-0.5">
        {person.sample_count} {t("gallery.samples")}
      </p>
      {person.avg_accuracy != null && (
        <p className="text-xs text-muted-foreground mt-0.5">
          Avg: <span className="font-medium text-foreground">{person.avg_accuracy}%</span>
        </p>
      )}
      <Badge
        variant="outline"
        className="mt-2 text-[10px] bg-success/10 text-success border-success/30"
      >
        {t("events.authorized")}
      </Badge>
      <div className="flex gap-2 mt-3 justify-center">
        <Button size="sm" variant="ghost" onClick={onViewSamples}>
          <Images className="h-3.5 w-3.5 mr-1" />
          {t("gallery.viewSamples")}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="text-danger hover:text-danger"
          onClick={onDelete}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
    </Card>
  );
}

/* ---------- View samples dialog ---------- */
function ViewSamplesDialog({
  person,
  open,
  onOpenChange,
}: {
  person: Person | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const { t } = useTranslation();
  const samplesQ = useQuery({
    queryKey: ["person-samples", person?.id],
    queryFn: () => fetchPersonSamples(person!.id),
    enabled: open && !!person,
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {person?.name} — {t("gallery.viewSamples")}
          </DialogTitle>
        </DialogHeader>

        {samplesQ.isLoading ? (
          <div className="grid grid-cols-3 gap-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="aspect-square bg-muted animate-pulse rounded-md" />
            ))}
          </div>
        ) : samplesQ.data?.length ? (
          <div className="grid grid-cols-3 sm:grid-cols-4 gap-3 max-h-[60vh] overflow-y-auto pr-1">
            {samplesQ.data.map((url, i) => (
              <div key={i} className="aspect-square overflow-hidden rounded-md border bg-muted">
                <img
                  src={url.startsWith("http") ? url : `${API_BASE_URL}/${url}`}
                  className="w-full h-full object-cover"
                  alt={`Sample ${i + 1}`}
                />
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-10 text-sm text-muted-foreground">
            {t("gallery.noSamples")}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.close")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ---------- Add person dialog ---------- */
function AddPersonDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [files, setFiles] = useState<File[]>([]);

  const mut = useMutation({
    mutationFn: () => createPerson(name, files),
    onSuccess: () => {
      toast.success(t("common.saved"));
      void qc.invalidateQueries({ queryKey: ["persons"] });
      onOpenChange(false);
      setName("");
      setFiles([]);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("gallery.addPerson")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <label className="text-xs font-medium mb-1 block">{t("gallery.fullName")}</label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("gallery.fullName")}
            />
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">{t("events.snapshot")}</label>
            <label className="border-2 border-dashed rounded-md p-6 flex flex-col items-center justify-center cursor-pointer hover:bg-muted/30">
              <Upload className="h-6 w-6 text-muted-foreground mb-2" />
              <span className="text-xs text-muted-foreground">
                JPG, PNG · multiple allowed
              </span>
              <input
                type="file"
                accept="image/*"
                multiple
                className="hidden"
                onChange={(e) => setFiles(Array.from(e.target.files || []))}
              />
            </label>
            {files.length > 0 && (
              <p className="text-xs text-muted-foreground mt-2">
                {files.length} file(s) selected
              </p>
            )}
            <p className="text-[11px] text-muted-foreground mt-2">
              {t("gallery.uploadHint")}
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => mut.mutate()} disabled={!name || mut.isPending}>
            {t("gallery.savePerson")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
