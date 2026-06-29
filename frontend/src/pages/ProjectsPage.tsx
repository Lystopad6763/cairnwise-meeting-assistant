import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRight,
  CalendarDays,
  FolderKanban,
  FolderPlus,
  Plus,
  RefreshCw,
  ServerCrash,
} from 'lucide-react';

import { cn } from '../lib/cn';
import { useProjects, useCreateProject } from '../lib/queries';
import { ApiError } from '../lib/api';
import { formatDate } from '../lib/format';
import type { ProjectIn, ProjectOut } from '../types';

import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  Modal,
  Skeleton,
  Textarea,
  useToast,
} from '../components/ui';

// ---------------------------------------------------------------------------
// Slug helpers
// ---------------------------------------------------------------------------

/**
 * Derive a URL-safe slug from a free-text name.
 * - lowercases, transliterates basic Cyrillic → Latin, trims, hyphenates.
 * Used to auto-suggest the slug while the user types the project name.
 */
const CYRILLIC_MAP: Record<string, string> = {
  а: 'a', б: 'b', в: 'v', г: 'h', ґ: 'g', д: 'd', е: 'e', є: 'ie', ж: 'zh',
  з: 'z', и: 'y', і: 'i', ї: 'i', й: 'i', к: 'k', л: 'l', м: 'm', н: 'n',
  о: 'o', п: 'p', р: 'r', с: 's', т: 't', у: 'u', ф: 'f', х: 'kh', ц: 'ts',
  ч: 'ch', ш: 'sh', щ: 'shch', ь: '', ю: 'iu', я: 'ia', ъ: '', ы: 'y', э: 'e', ё: 'e',
};

export function slugify(input: string): string {
  return input
    .toLowerCase()
    .trim()
    .split('')
    .map((ch) => CYRILLIC_MAP[ch] ?? ch)
    .join('')
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '') // strip diacritics
    .replace(/[^a-z0-9]+/g, '-') // non-alnum → hyphen
    .replace(/^-+|-+$/g, '') // trim hyphens
    .replace(/-{2,}/g, '-') // collapse repeats
    .slice(0, 60);
}

const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

// ---------------------------------------------------------------------------
// Project card
// ---------------------------------------------------------------------------

function ProjectCard({ project }: { project: ProjectOut }) {
  const navigate = useNavigate();
  const go = useCallback(
    () => navigate(`/projects/${project.id}`),
    [navigate, project.id],
  );

  return (
    <Card
      as="article"
      interactive
      role="link"
      tabIndex={0}
      aria-label={`Відкрити проєкт ${project.name}`}
      onClick={go}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          go();
        }
      }}
      className="group flex h-full flex-col gap-3 p-5 focus-visible:ring-2 focus-visible:ring-brand"
    >
      <div className="flex items-start justify-between gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-card bg-brand/15 text-brand">
          <FolderKanban className="h-5 w-5" aria-hidden="true" />
        </span>
        <ArrowRight
          className="h-4 w-4 shrink-0 -translate-x-1 text-muted opacity-0 transition-all group-hover:translate-x-0 group-hover:text-brand group-hover:opacity-100"
          aria-hidden="true"
        />
      </div>

      <div className="min-w-0 flex-1">
        <h3
          className="truncate text-base font-semibold text-fg transition-colors group-hover:text-brand"
          title={project.name}
        >
          {project.name}
        </h3>
        {project.description ? (
          <p className="mt-1 line-clamp-2 text-sm text-muted">{project.description}</p>
        ) : (
          <p className="mt-1 text-sm text-muted/60">Без опису</p>
        )}
      </div>

      <div className="flex items-center justify-between gap-2 pt-1">
        <Badge tone="brand" className="max-w-[60%] truncate font-mono">
          {project.slug}
        </Badge>
        <span className="inline-flex items-center gap-1 text-xs text-muted">
          <CalendarDays className="h-3.5 w-3.5" aria-hidden="true" />
          {formatDate(project.created_at)}
        </span>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Create-project dialog
// ---------------------------------------------------------------------------

interface CreateProjectDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated: (project: ProjectOut) => void;
}

function CreateProjectDialog({ open, onClose, onCreated }: CreateProjectDialogProps) {
  const { toast } = useToast();
  const create = useCreateProject();

  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [description, setDescription] = useState('');

  // True once the user has hand-edited the slug — stop auto-suggesting then.
  const [slugTouched, setSlugTouched] = useState(false);

  const [nameError, setNameError] = useState<string | null>(null);
  const [slugError, setSlugError] = useState<string | null>(null);

  const pending = create.isPending;

  const reset = useCallback(() => {
    setName('');
    setSlug('');
    setDescription('');
    setSlugTouched(false);
    setNameError(null);
    setSlugError(null);
    create.reset();
  }, [create]);

  // Reset form state whenever the dialog is (re)opened.
  useEffect(() => {
    if (open) reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const onNameChange = useCallback(
    (value: string) => {
      setName(value);
      if (nameError) setNameError(null);
      if (!slugTouched) {
        setSlug(slugify(value));
        setSlugError(null);
      }
    },
    [nameError, slugTouched],
  );

  const onSlugChange = useCallback(
    (value: string) => {
      setSlugTouched(true);
      // Keep slug typing constrained to the URL-safe alphabet as you go.
      const next = value
        .toLowerCase()
        .replace(/[^a-z0-9-]/g, '-')
        .replace(/-{2,}/g, '-');
      setSlug(next);
      if (slugError) setSlugError(null);
    },
    [slugError],
  );

  const handleSubmit = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      const trimmedName = name.trim();
      const trimmedSlug = slug.trim().replace(/^-+|-+$/g, '');

      let bad = false;
      if (!trimmedName) {
        setNameError('Вкажіть назву проєкту');
        bad = true;
      }
      if (!trimmedSlug) {
        setSlugError('Вкажіть slug');
        bad = true;
      } else if (!SLUG_RE.test(trimmedSlug)) {
        setSlugError('Лише малі літери, цифри та дефіси (напр., team-sync)');
        bad = true;
      }
      if (bad) return;

      const body: ProjectIn = {
        slug: trimmedSlug,
        name: trimmedName,
        description: description.trim() || null,
      };

      create.mutate(body, {
        onSuccess: (project) => {
          toast({
            title: 'Проєкт створено',
            description: project.name,
            tone: 'success',
          });
          onCreated(project);
        },
        onError: (err: ApiError) => {
          if (err.status === 409) {
            // Duplicate slug → inline error on the slug field (per contract §5).
            setSlugError('Цей slug вже зайнятий, оберіть інший');
            return;
          }
          if (err.status === 422) {
            setSlugError(err.detail || 'Некоректні дані форми');
            return;
          }
          toast({
            title: 'Не вдалося створити проєкт',
            description:
              err.status === 0
                ? 'Бекенд недоступний. Перевірте з’єднання.'
                : err.detail || 'Спробуйте ще раз пізніше.',
            tone: 'danger',
          });
        },
      });
    },
    [name, slug, description, create, toast, onCreated],
  );

  return (
    <Modal
      open={open}
      onClose={pending ? () => {} : onClose}
      title="Новий проєкт"
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={pending}>
            Скасувати
          </Button>
          <Button
            variant="primary"
            icon={Plus}
            loading={pending}
            // Submits the form below by id association.
            type="submit"
            form="create-project-form"
          >
            Створити проєкт
          </Button>
        </>
      }
    >
      <form
        id="create-project-form"
        onSubmit={handleSubmit}
        className="flex flex-col gap-4"
        noValidate
      >
        <Input
          label="Назва"
          placeholder="Напр., Синки команди Альфа"
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          error={nameError ?? undefined}
          disabled={pending}
          autoFocus
          maxLength={120}
        />

        <Input
          label="Slug"
          placeholder="team-alpha"
          value={slug}
          onChange={(e) => onSlugChange(e.target.value)}
          error={slugError ?? undefined}
          hint={
            slugError
              ? undefined
              : 'Унікальний ідентифікатор в URL: малі літери, цифри, дефіси.'
          }
          disabled={pending}
          className="font-mono"
          maxLength={60}
          autoComplete="off"
          spellCheck={false}
        />

        <Textarea
          label="Опис (необов’язково)"
          placeholder="Коротко про мету проєкту та учасників."
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          disabled={pending}
          rows={3}
          maxLength={500}
        />
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Loading / error / empty states
// ---------------------------------------------------------------------------

function ProjectsGridSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <Card key={i} className="flex flex-col gap-3 p-5">
          <Skeleton className="h-10 w-10 rounded-card" />
          <Skeleton className="h-5 w-3/4" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
          <div className="flex items-center justify-between pt-1">
            <Skeleton className="h-5 w-20" />
            <Skeleton className="h-4 w-24" />
          </div>
        </Card>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function ProjectsPage() {
  const projects = useProjects();
  const [dialogOpen, setDialogOpen] = useState(false);
  const navigate = useNavigate();

  const openDialog = useCallback(() => setDialogOpen(true), []);
  const closeDialog = useCallback(() => setDialogOpen(false), []);

  const onCreated = useCallback(
    (project: ProjectOut) => {
      setDialogOpen(false);
      // React Query invalidates the list (via useCreateProject); jump straight
      // into the freshly created project so the user can start uploading.
      navigate(`/projects/${project.id}`);
    },
    [navigate],
  );

  const rows = projects.data ?? [];
  const count = rows.length;

  const sorted = useMemo(
    () =>
      [...rows].sort(
        (a, b) =>
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      ),
    [rows],
  );

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-semibold tracking-tight text-fg">Проєкти</h1>
            {count > 0 && <Badge tone="neutral">{count}</Badge>}
          </div>
          <p className="text-sm text-muted">
            Робочі простори зустрічей: завантаження записів, транскрипція та (скоро)
            AI-резюме.
          </p>
        </div>

        <Button variant="primary" icon={Plus} onClick={openDialog}>
          Новий проєкт
        </Button>
      </header>

      {/* Body */}
      {projects.isLoading ? (
        <ProjectsGridSkeleton />
      ) : projects.isError ? (
        <EmptyState
          icon={ServerCrash}
          title="Не вдалося завантажити проєкти"
          description={
            projects.error.status === 0
              ? 'Бекенд недоступний. Перевірте з’єднання та спробуйте ще раз.'
              : projects.error.detail || 'Сталася помилка під час завантаження.'
          }
          action={
            <Button
              variant="secondary"
              icon={RefreshCw}
              loading={projects.isFetching}
              onClick={() => projects.refetch()}
            >
              Повторити
            </Button>
          }
        />
      ) : count === 0 ? (
        <EmptyState
          icon={FolderPlus}
          title="Ще немає проєктів"
          description="Створіть перший проєкт, щоб завантажувати записи зустрічей і отримувати транскрипти. Усе впорядковано за проєктами."
          action={
            <Button variant="primary" icon={Plus} onClick={openDialog}>
              Створити проєкт
            </Button>
          }
        />
      ) : (
        <div
          className={cn(
            'grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3',
            // Subtle hint that the list is auto-refreshing in the background.
            projects.isFetching && 'opacity-95',
          )}
        >
          {sorted.map((p) => (
            <ProjectCard key={p.id} project={p} />
          ))}
        </div>
      )}

      {/* Create dialog */}
      <CreateProjectDialog
        open={dialogOpen}
        onClose={closeDialog}
        onCreated={onCreated}
      />
    </div>
  );
}

export default ProjectsPage;
