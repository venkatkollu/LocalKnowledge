import type { LucideIcon } from "lucide-react";
import {
  Activity,
  BarChart3,
  Boxes,
  Database,
  FileStack,
  Gauge,
  Layers,
  MessagesSquare,
  RefreshCcw,
  Settings,
  SlidersHorizontal,
} from "lucide-react";

export interface NavItem {
  label: string;
  icon: LucideIcon;
  /** Route for shipped sections; omitted while a section is still planned. */
  to?: string;
  /** Planned release, e.g. "v2". Omitted once the section ships. */
  ships?: string;
}

export interface NavSection {
  title: string;
  items: NavItem[];
}

/** Navigation for the product interface. */
export const NAV_SECTIONS: NavSection[] = [
  {
    title: "Workspace",
    items: [
      { label: "Ask Knowledge", icon: MessagesSquare, to: "/" },
      { label: "Documents", icon: FileStack, to: "/documents" },
      { label: "Collections", icon: Layers, to: "/collections" },
      { label: "Sync Queue", icon: RefreshCcw, to: "/sync" },
    ],
  },
  {
    title: "Observability",
    items: [
      { label: "Activity", icon: Activity, to: "/activity" },
      { label: "Performance", icon: Gauge, to: "/performance" },
      { label: "Evaluations", icon: BarChart3, to: "/evaluations" },
    ],
  },
  {
    title: "System",
    items: [
      { label: "Models", icon: SlidersHorizontal, to: "/models" },
      { label: "Indexes", icon: Boxes, to: "/indexes" },
      { label: "Settings", icon: Settings, to: "/settings" },
      { label: "Storage", icon: Database, to: "/storage" },
    ],
  },
];
