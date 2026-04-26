"use client";

// Phase 3.A KB tree browser.
//
// Two-pane layout:
//
//   left (280px): folder tree, indented 16px per level, expand/collapse,
//     drag-reparent via HTML5 drag/drop (native — no 3rd-party dep). The
//     service owns cycle detection; the frontend only translates a 409
//     response into a toast, so we never have to re-implement the
//     ancestor walk client-side. The drop target lights up on
//     dragOver; invalid moves are only detected by the server.
//   right: when a folder is selected → items table (title, kind,
//     updated_at, license badge). When a row is clicked → navigate to
//     `/projects/[id]/kb/[itemId]` (the existing detail page owns the
//     per-item license dropdown; we don't reimplement it here).
//
// Reused primitives: Button, Card, EmptyState, Heading, Text. No
// inline styles beyond layout-only tweaks that the design system
// explicitly allows (margins, widths, flex directions).
//
// Search + language filter chips from the old KbList are preserved at
// the top of the right pane; they filter the currently-selected
// folder's items in-memory so keystrokes don't hit the backend
// (the tree endpoint is cheap but not keystroke-cheap).

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { Button, Card, EmptyState, Heading, Text } from "@/components/ui";
import {
  ApiError,
  createKbFolder,
  deleteKbFolder,
  getKbTree,
  type KbFolderNode,
  type KbTreeItem,
  type KbTreeResponse,
  moveKbItem,
  reparentKbFolder,
} from "@/lib/api";

type Role = "owner" | "member" | "observer";
type Tier = "full" | "task_scoped" | "observer";

// Filter matches the existing flat-list chips — preserved per brief.
const SOURCE_FILTERS = [
  "all",
  "wiki",
  "git",
  "rss",
  "user-drop",
] as const;
type SourceFilter = (typeof SOURCE_FILTERS)[number];

interface Props {
  projectId: string;
  initialTree: KbTreeResponse;
  role: Role;
  tier: Tier;
}

export function KbTreeBrowser({
  projectId,
  initialTree,
  role,
  tier,
}: Props) {
  const t = useTranslations();
  const locale = useLocale();

  const [tree, setTree] = useState<KbTreeResponse>(initialTree);
  const [selectedFolderId, setSelectedFolderId] = useState<string | null>(
    initialTree.root_id,
  );
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(initialTree.root_id ? [initialTree.root_id] : []),
  );
  const [search, setSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [toast, setToast] = useState<string | null>(null);

  const isOwner = role === "owner";
  const canCreateFolder = tier === "full";

  // ---- refresh --------------------------------------------------------

  const refresh = useCallback(async () => {
    try {
      const fresh = await getKbTree(projectId);
      setTree(fresh);
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "refresh failed";
      setToast(msg);
    }
  }, [projectId]);

  const flashToast = useCallback((msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(null), 2800);
  }, []);

  // ---- tree indexing --------------------------------------------------

  const childrenByParent = useMemo(() => {
    const map = new Map<string | null, KbFolderNode[]>();
    for (const f of tree.folders) {
      const key = f.parent_folder_id;
      const arr = map.get(key) ?? [];
      arr.push(f);
      map.set(key, arr);
    }
    for (const arr of map.values()) {
      arr.sort((a, b) => a.name.localeCompare(b.name));
    }
    return map;
  }, [tree.folders]);

  const itemsByFolder = useMemo(() => {
    const map = new Map<string, KbTreeItem[]>();
    for (const item of tree.items) {
      const key = item.folder_id ?? tree.root_id ?? "__orphan__";
      const arr = map.get(key) ?? [];
      arr.push(item);
      map.set(key, arr);
    }
    return map;
  }, [tree.items, tree.root_id]);

  const folderById = useMemo(() => {
    const map = new Map<string, KbFolderNode>();
    for (const f of tree.folders) map.set(f.id, f);
    return map;
  }, [tree.folders]);

  const selectedFolder = selectedFolderId
    ? folderById.get(selectedFolderId) ?? null
    : null;

  // ---- actions --------------------------------------------------------

  const toggleExpand = (folderId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(folderId)) next.delete(folderId);
      else next.add(folderId);
      return next;
    });
  };

  const handleCreateFolder = async () => {
    if (!canCreateFolder) {
      // Button is disabled in this state, but keep a defensive toast so
      // a non-full-tier caller who somehow got here sees why. Matches
      // the backend's 403 `forbidden` response on the same gate.
      flashToast(t("kb.folder.requireFullTier"));
      return;
    }
    const parent =
      selectedFolderId ?? tree.root_id ?? null;
    if (!parent) {
      flashToast(t("kb.folder.createFailed"));
      return;
    }
    const name = window.prompt(
      t("kb.folder.newPlaceholder"),
      "",
    );
    if (!name || !name.trim()) return;
    try {
      await createKbFolder(projectId, {
        name: name.trim(),
        parent_folder_id: parent,
      });
      await refresh();
      setExpanded((prev) => {
        const next = new Set(prev);
        next.add(parent);
        return next;
      });
    } catch (err) {
      // Surface EVERY backend error as a toast — before, only 409 had a
      // user-visible message and other failures (403 forbidden, 400
      // name_required, network errors) silently no-op'd, which is the
      // "fails silently" bug users reported in v4 dogfood.
      if (err instanceof ApiError && err.status === 409) {
        flashToast(t("kb.folder.nameConflict"));
      } else if (err instanceof ApiError && err.status === 403) {
        flashToast(t("kb.folder.requireFullTier"));
      } else {
        flashToast(t("kb.folder.createFailed"));
      }
    }
  };

  const handleDeleteFolder = async (folderId: string) => {
    if (!isOwner) return;
    if (!window.confirm(t("kb.folder.confirmDelete"))) return;
    try {
      await deleteKbFolder(projectId, folderId);
      if (selectedFolderId === folderId) {
        setSelectedFolderId(tree.root_id);
      }
      await refresh();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        flashToast(t("kb.folder.notEmpty"));
      } else {
        flashToast(t("kb.folder.deleteFailed"));
      }
    }
  };

  const handleReparent = async (
    folderId: string,
    newParentId: string | null,
  ) => {
    if (!isOwner) return;
    if (folderId === newParentId) return;
    try {
      await reparentKbFolder(projectId, folderId, newParentId);
      await refresh();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        flashToast(t("kb.folder.cycleRejected"));
      } else {
        flashToast(t("kb.folder.moveFailed"));
      }
    }
  };

  const handleMoveItem = async (
    itemId: string,
    folderId: string,
  ) => {
    try {
      await moveKbItem(projectId, itemId, folderId);
      await refresh();
    } catch (err) {
      flashToast(
        err instanceof ApiError
          ? t("kb.folder.moveFailed")
          : t("kb.folder.moveFailed"),
      );
    }
  };

  // ---- right-pane items ----------------------------------------------

  const items = useMemo(() => {
    if (!selectedFolderId) return [];
    const raw = itemsByFolder.get(selectedFolderId) ?? [];
    const q = search.trim().toLowerCase();
    const localeTag = `lang:${locale}`;
    return raw.filter((item) => {
      // Wiki items are ingested in both languages; show only the
      // viewer's locale — mirrors the flat-list behavior.
      if (item.source_kind === "wiki") {
        if (!item.tags.includes(localeTag)) return false;
      }
      if (
        sourceFilter !== "all" &&
        !matchesSource(item.source_kind, sourceFilter)
      ) {
        return false;
      }
      if (q) {
        const hay =
          `${item.title} ${item.summary} ${item.tags.join(" ")} ${
            item.source_identifier ?? ""
          }`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [
    itemsByFolder,
    selectedFolderId,
    search,
    sourceFilter,
    locale,
  ]);

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "280px minmax(0, 1fr)",
        gap: 16,
        alignItems: "start",
      }}
    >
      <Card title={t("kb.folder.treeTitle")}>
        <FolderTree
          rootId={tree.root_id}
          childrenByParent={childrenByParent}
          folderById={folderById}
          selectedFolderId={selectedFolderId}
          expanded={expanded}
          onSelect={setSelectedFolderId}
          onToggleExpand={toggleExpand}
          onReparent={handleReparent}
          onMoveItem={handleMoveItem}
          onDelete={handleDeleteFolder}
          canReparent={isOwner}
          canDelete={isOwner}
          t={t}
        />
      </Card>

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 12,
          minWidth: 0,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            justifyContent: "space-between",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          <Heading level={2}>
            {selectedFolder
              ? folderBreadcrumb(selectedFolder, folderById)
              : t("kb.folder.selectPrompt")}
          </Heading>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleCreateFolder}
              disabled={!canCreateFolder || !selectedFolderId}
              title={
                canCreateFolder
                  ? undefined
                  : t("kb.folder.requireFullTier")
              }
            >
              {t("kb.folder.new")}
            </Button>
            {/* "New item" previously linked to /projects/[id]/membrane,
                but that route doesn't exist. Ingest is managed from the
                project settings page, specifically the "External signal
                subscriptions" section. We anchor-link straight to that
                section so the user doesn't land on the page-top gate-
                keeper map and wonder what "sign-off gate-keepers" has
                to do with creating a KB entry (it doesn't). */}
            <Link
              href={`/projects/${projectId}/settings#membrane-subscriptions`}
              style={{ textDecoration: "none" }}
              title={t("kb.folder.newItemHelp")}
            >
              <Button variant="ghost" size="sm">
                {t("kb.folder.newItem")}
              </Button>
            </Link>
          </div>
        </div>

        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t("kb.search")}
          aria-label={t("kb.search")}
          style={{
            width: "100%",
            padding: "10px 12px",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            fontSize: 14,
            fontFamily: "inherit",
            background: "#fff",
            color: "var(--wg-ink)",
            boxSizing: "border-box",
          }}
        />

        <div
          role="tablist"
          aria-label={t("kb.title")}
          style={{ display: "flex", gap: 6, flexWrap: "wrap" }}
        >
          {SOURCE_FILTERS.map((f) => {
            const active = sourceFilter === f;
            return (
              <button
                key={f}
                role="tab"
                aria-selected={active}
                onClick={() => setSourceFilter(f)}
                style={{
                  padding: "4px 12px",
                  fontSize: 12,
                  fontFamily: "var(--wg-font-mono)",
                  border: "1px solid var(--wg-line)",
                  background: active ? "var(--wg-ink)" : "#fff",
                  color: active ? "#fff" : "var(--wg-ink)",
                  borderRadius: 999,
                  cursor: "pointer",
                }}
              >
                {t(`kb.filters.${f}`)}
              </button>
            );
          })}
        </div>

        {items.length === 0 ? (
          <EmptyState>{t("kb.empty")}</EmptyState>
        ) : (
          <ItemsTable
            projectId={projectId}
            items={items}
            t={t}
          />
        )}
      </div>

      {toast ? (
        <div
          role="status"
          aria-live="polite"
          style={{
            position: "fixed",
            bottom: 24,
            right: 24,
            padding: "10px 14px",
            background: "var(--wg-accent)",
            color: "#fff",
            borderRadius: "var(--wg-radius)",
            fontSize: 13,
            fontFamily: "var(--wg-font-mono)",
            boxShadow: "0 4px 12px rgba(0,0,0,0.12)",
            zIndex: 40,
          }}
        >
          {toast}
        </div>
      ) : null}
    </div>
  );
}

// ---- FolderTree -----------------------------------------------------

function FolderTree({
  rootId,
  childrenByParent,
  folderById,
  selectedFolderId,
  expanded,
  onSelect,
  onToggleExpand,
  onReparent,
  onMoveItem,
  onDelete,
  canReparent,
  canDelete,
  t,
}: {
  rootId: string | null;
  childrenByParent: Map<string | null, KbFolderNode[]>;
  folderById: Map<string, KbFolderNode>;
  selectedFolderId: string | null;
  expanded: Set<string>;
  onSelect: (id: string) => void;
  onToggleExpand: (id: string) => void;
  onReparent: (folderId: string, newParentId: string | null) => void;
  onMoveItem: (itemId: string, folderId: string) => void;
  onDelete: (folderId: string) => void;
  canReparent: boolean;
  canDelete: boolean;
  t: ReturnType<typeof useTranslations>;
}) {
  if (!rootId) {
    return <EmptyState>{t("kb.folder.empty")}</EmptyState>;
  }
  const root = folderById.get(rootId);
  if (!root) return null;

  return (
    <div role="tree" style={{ display: "flex", flexDirection: "column" }}>
      <FolderNode
        folder={root}
        depth={0}
        childrenByParent={childrenByParent}
        selectedFolderId={selectedFolderId}
        expanded={expanded}
        onSelect={onSelect}
        onToggleExpand={onToggleExpand}
        onReparent={onReparent}
        onMoveItem={onMoveItem}
        onDelete={onDelete}
        canReparent={canReparent}
        canDelete={canDelete}
        t={t}
      />
    </div>
  );
}

function FolderNode({
  folder,
  depth,
  childrenByParent,
  selectedFolderId,
  expanded,
  onSelect,
  onToggleExpand,
  onReparent,
  onMoveItem,
  onDelete,
  canReparent,
  canDelete,
  t,
}: {
  folder: KbFolderNode;
  depth: number;
  childrenByParent: Map<string | null, KbFolderNode[]>;
  selectedFolderId: string | null;
  expanded: Set<string>;
  onSelect: (id: string) => void;
  onToggleExpand: (id: string) => void;
  onReparent: (folderId: string, newParentId: string | null) => void;
  onMoveItem: (itemId: string, folderId: string) => void;
  onDelete: (folderId: string) => void;
  canReparent: boolean;
  canDelete: boolean;
  t: ReturnType<typeof useTranslations>;
}) {
  const children = childrenByParent.get(folder.id) ?? [];
  const isExpanded = expanded.has(folder.id);
  const isSelected = selectedFolderId === folder.id;
  const isRoot = folder.parent_folder_id === null;
  const label = isRoot ? t("kb.folder.root") : folder.name;
  const [dragOver, setDragOver] = useState(false);

  const onDragStart = (e: React.DragEvent) => {
    if (!canReparent || isRoot) {
      e.preventDefault();
      return;
    }
    e.dataTransfer.setData(
      "application/x-wg-folder",
      folder.id,
    );
    e.dataTransfer.effectAllowed = "move";
  };

  const onDragOver = (e: React.DragEvent) => {
    // We accept both folders and items. Need preventDefault on both
    // dragover + drop for the browser to fire our drop handler.
    if (
      e.dataTransfer.types.includes("application/x-wg-folder") ||
      e.dataTransfer.types.includes("application/x-wg-item")
    ) {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      setDragOver(true);
    }
  };

  const onDragLeave = () => setDragOver(false);

  const onDrop = (e: React.DragEvent) => {
    setDragOver(false);
    const folderId = e.dataTransfer.getData(
      "application/x-wg-folder",
    );
    if (folderId && folderId !== folder.id) {
      e.preventDefault();
      onReparent(folderId, folder.id);
      return;
    }
    const itemId = e.dataTransfer.getData(
      "application/x-wg-item",
    );
    if (itemId) {
      e.preventDefault();
      onMoveItem(itemId, folder.id);
    }
  };

  return (
    <div>
      <div
        role="treeitem"
        aria-selected={isSelected}
        aria-expanded={children.length > 0 ? isExpanded : undefined}
        draggable={canReparent && !isRoot}
        onDragStart={onDragStart}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={() => onSelect(folder.id)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 4,
          paddingLeft: 8 + depth * 16,
          paddingRight: 8,
          paddingTop: 4,
          paddingBottom: 4,
          background: isSelected
            ? "var(--wg-surface)"
            : dragOver
              ? "var(--wg-surface-sunk, #f4f4f4)"
              : "transparent",
          borderLeft: isSelected
            ? "2px solid var(--wg-accent)"
            : "2px solid transparent",
          cursor: "pointer",
          fontSize: 13,
          color: "var(--wg-ink)",
          userSelect: "none",
        }}
      >
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onToggleExpand(folder.id);
          }}
          aria-label={
            isExpanded ? t("kb.folder.collapse") : t("kb.folder.expand")
          }
          style={{
            width: 16,
            height: 16,
            border: "none",
            background: "transparent",
            cursor: "pointer",
            color: "var(--wg-ink-soft)",
            fontSize: 10,
            padding: 0,
          }}
        >
          {children.length > 0 ? (isExpanded ? "▾" : "▸") : ""}
        </button>
        <span
          style={{
            flex: 1,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {label}
        </span>
        {canDelete && !isRoot ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onDelete(folder.id);
            }}
            title={t("kb.folder.delete")}
            style={{
              border: "none",
              background: "transparent",
              cursor: "pointer",
              color: "var(--wg-ink-soft)",
              fontSize: 11,
              padding: "0 2px",
            }}
          >
            ×
          </button>
        ) : null}
      </div>
      {children.length > 0 && isExpanded ? (
        <div role="group">
          {children.map((c) => (
            <FolderNode
              key={c.id}
              folder={c}
              depth={depth + 1}
              childrenByParent={childrenByParent}
              selectedFolderId={selectedFolderId}
              expanded={expanded}
              onSelect={onSelect}
              onToggleExpand={onToggleExpand}
              onReparent={onReparent}
              onMoveItem={onMoveItem}
              onDelete={onDelete}
              canReparent={canReparent}
              canDelete={canDelete}
              t={t}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

// ---- ItemsTable -----------------------------------------------------

function ItemsTable({
  projectId,
  items,
  t,
}: {
  projectId: string;
  items: KbTreeItem[];
  t: ReturnType<typeof useTranslations>;
}) {
  return (
    <Card flush>
      <div
        role="table"
        aria-label={t("kb.folder.itemsTable")}
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 3fr) minmax(80px, 1fr) minmax(100px, 1fr) minmax(80px, 1fr)",
          fontSize: 13,
          color: "var(--wg-ink)",
        }}
      >
        <TableHeader t={t} />
        {items.map((item) => (
          <ItemRow
            key={item.id}
            projectId={projectId}
            item={item}
            t={t}
          />
        ))}
      </div>
    </Card>
  );
}

function TableHeader({
  t,
}: {
  t: ReturnType<typeof useTranslations>;
}) {
  const cellStyle: React.CSSProperties = {
    padding: "8px 12px",
    fontSize: 10,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
    color: "var(--wg-ink-soft)",
    fontWeight: 600,
    borderBottom: "1px solid var(--wg-line)",
    background: "var(--wg-surface)",
  };
  return (
    <>
      <div role="columnheader" style={cellStyle}>
        {t("kb.folder.colTitle")}
      </div>
      <div role="columnheader" style={cellStyle}>
        {t("kb.folder.colKind")}
      </div>
      <div role="columnheader" style={cellStyle}>
        {t("kb.folder.colUpdated")}
      </div>
      <div role="columnheader" style={cellStyle}>
        {t("kb.folder.colLicense")}
      </div>
    </>
  );
}

function ItemRow({
  projectId,
  item,
  t,
}: {
  projectId: string;
  item: KbTreeItem;
  t: ReturnType<typeof useTranslations>;
}) {
  const cellStyle: React.CSSProperties = {
    padding: "10px 12px",
    borderBottom: "1px solid var(--wg-line-soft)",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  };

  const onDragStart = (e: React.DragEvent) => {
    e.dataTransfer.setData("application/x-wg-item", item.id);
    e.dataTransfer.effectAllowed = "move";
  };

  return (
    <>
      <div
        role="cell"
        style={cellStyle}
        draggable
        onDragStart={onDragStart}
      >
        <Link
          href={`/projects/${projectId}/kb/${item.id}`}
          style={{
            color: "var(--wg-ink)",
            textDecoration: "none",
            fontWeight: 500,
          }}
        >
          {item.title || item.summary || item.source_identifier}
        </Link>
        {item.status === "draft" || item.status === "pending-review" ? (
          // Membrane staging signal — the row is in the cell's
          // membrane, not the cell proper. Lets readers see "this
          // is queued for owner review" without opening the detail.
          <DraftChip status={item.status} t={t} />
        ) : null}
      </div>
      <div role="cell" style={cellStyle}>
        <SourceBadge kind={item.source_kind} />
      </div>
      <div
        role="cell"
        style={{
          ...cellStyle,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-soft)",
          fontSize: 11,
        }}
      >
        {relativeTime(item.updated_at || item.created_at)}
      </div>
      <div role="cell" style={cellStyle}>
        <LicenseBadge tier={item.license_tier_override} t={t} />
      </div>
    </>
  );
}

function DraftChip({
  status,
  t,
}: {
  status: string;
  t: ReturnType<typeof useTranslations>;
}) {
  // pending-review (signals) and draft (group KB writes deferred by
  // membrane) both surface as the same "not yet canonical" chip —
  // user-facing intent is identical. Different colors keep the
  // ingest path distinguishable from the user-write path.
  const isPending = status === "pending-review";
  return (
    <span
      data-testid="kb-draft-chip"
      style={{
        marginLeft: 8,
        fontSize: 9,
        fontFamily: "var(--wg-font-mono)",
        padding: "1px 6px",
        borderRadius: 10,
        border: `1px solid ${isPending ? "var(--wg-amber)" : "var(--wg-ink-soft)"}`,
        color: isPending ? "var(--wg-amber)" : "var(--wg-ink-soft)",
        letterSpacing: "0.04em",
        textTransform: "uppercase",
        verticalAlign: "middle",
      }}
    >
      {isPending
        ? t("kb.statusChip.pendingReview")
        : t("kb.statusChip.draft")}
    </span>
  );
}

function SourceBadge({ kind }: { kind: string }) {
  const normalized = (kind || "").toLowerCase();
  return (
    <span
      style={{
        fontSize: 10,
        fontFamily: "var(--wg-font-mono)",
        padding: "1px 8px",
        borderRadius: 10,
        background: "var(--wg-ink)",
        color: "#fff",
        letterSpacing: "0.04em",
        textTransform: "uppercase",
      }}
    >
      {normalized || "kb"}
    </span>
  );
}

function LicenseBadge({
  tier,
  t,
}: {
  tier: "full" | "task_scoped" | "observer" | null;
  t: ReturnType<typeof useTranslations>;
}) {
  if (tier === null) {
    return (
      <Text variant="caption" muted>
        {t("kb.license.inherit")}
      </Text>
    );
  }
  const color =
    tier === "observer"
      ? "var(--wg-amber)"
      : tier === "task_scoped"
        ? "var(--wg-ink-soft)"
        : "var(--wg-ok)";
  return (
    <span
      style={{
        fontSize: 10,
        fontFamily: "var(--wg-font-mono)",
        padding: "1px 8px",
        borderRadius: 10,
        border: `1px solid ${color}`,
        color,
        letterSpacing: "0.04em",
        textTransform: "uppercase",
      }}
    >
      {t(`kb.license.tier.${tier}`)}
    </span>
  );
}

// ---- helpers --------------------------------------------------------

function matchesSource(kind: string, filter: SourceFilter): boolean {
  if (filter === "all") return true;
  if (filter === "git") return kind.startsWith("git");
  return kind === filter;
}

function folderBreadcrumb(
  folder: KbFolderNode,
  folderById: Map<string, KbFolderNode>,
): string {
  const parts: string[] = [folder.parent_folder_id === null ? "/" : folder.name];
  let cursor = folder.parent_folder_id;
  while (cursor) {
    const parent = folderById.get(cursor);
    if (!parent) break;
    if (parent.parent_folder_id === null) {
      parts.unshift("");
      break;
    }
    parts.unshift(parent.name);
    cursor = parent.parent_folder_id;
  }
  return parts.join(" / ");
}

function relativeTime(iso: string | null): string {
  if (!iso) return "";
  const tv = Date.parse(iso);
  if (Number.isNaN(tv)) return "";
  const delta = Math.max(0, Math.floor((Date.now() - tv) / 1000));
  if (delta < 60) return "just now";
  if (delta < 3600) return `${Math.floor(delta / 60)}m`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h`;
  if (delta < 86400 * 30) return `${Math.floor(delta / 86400)}d`;
  return new Date(tv).toLocaleDateString();
}
