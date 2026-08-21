import { useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Mail,
  MessageSquare,
  Package,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { apiRequest } from "./api";
import type { DashboardPermissions } from "./appTypes";

/**
 * Pantalla de inicio «Hoy» (portal): cuatro tarjetas accionables con conteos
 * reales del backend (`GET /today`, solo lectura). Cada tarjeta lleva a su
 * sección con un clic:
 *
 * - Aprobar propuestas → #aprobaciones
 * - Reenviar campañas pendientes → #clientes (pestaña Campañas)
 * - Reponer stock bajo → #catalogo
 * - Mensajes urgentes → #clientes (pestaña Escucha social)
 *
 * El RBAC decide qué tarjetas se muestran (aprobaciones solo con permiso
 * approve; campañas y mensajes viven bajo Clientes, solo con manage_leads).
 */

type TodayCard = {
  count: number | null;
  items: Array<{ label: string }>;
};

type TodayPayload = {
  cards: {
    pending_approvals: TodayCard;
    campaigns_pending_retry: TodayCard;
    low_stock: TodayCard;
    urgent_messages: TodayCard;
    engine_failures: TodayCard;
  };
};

function openClientesTab(tab: string) {
  sessionStorage.setItem("portal_clientes_tab", tab);
  window.location.hash = "clientes";
}

type CardProps = {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  count: number | null;
  items: Array<{ label: string }>;
  cta: string;
  onClick: () => void;
  tone: "action" | "ok";
};

function ActionCard({
  icon,
  title,
  subtitle,
  count,
  items,
  cta,
  onClick,
  tone,
}: CardProps) {
  const pending = count !== null && count > 0;
  return (
    <article className={`today-card ${pending ? "today-card-action" : ""}`}>
      <div className="today-card-head">
        <span className="today-card-icon">{icon}</span>
        <strong>{title}</strong>
        <span className={`badge ${pending ? "badge-orange" : "badge-green"}`}>
          {pending ? String(count) : "0"}
        </span>
      </div>
      <p className="muted">{subtitle}</p>
      {pending ? (
        <>
          <ul className="today-card-items">
            {items.slice(0, 3).map((item) => (
              <li key={item.label}>{item.label}</li>
            ))}
          </ul>
          <button type="button" className="today-card-cta" onClick={onClick}>
            {cta} <ArrowRight size={14} />
          </button>
        </>
      ) : (
        <p className={`today-card-ok ${tone === "ok" ? "ok" : ""}`}>
          <CheckCircle2 size={14} /> Todo en orden
        </p>
      )}
    </article>
  );
}

export function TodaySection({
  token,
  permissions,
}: {
  token: string;
  permissions: DashboardPermissions;
}) {
  const [data, setData] = useState<TodayPayload | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    apiRequest<TodayPayload>("/today", { token })
      .then((payload) => {
        if (!cancelled) setData(payload);
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (error) {
    return (
      <div className="alert error" role="alert">
        {error}
      </div>
    );
  }
  if (!data) {
    return <p className="muted" role="status">Cargando qué necesita tu atención…</p>;
  }

  const cards = data.cards;
  const visibleCards = [
    ...(permissions.approve
      ? [
          {
            key: "pending_approvals" as const,
            icon: <ShieldCheck size={20} />,
            title: "Aprobar propuestas",
            subtitle:
              "Los agentes han preparado acciones y esperan tu confirmación.",
            cta: "Ir a aprobaciones",
            onClick: () => {
              window.location.hash = "aprobaciones";
            },
          },
        ]
      : []),
    ...(permissions.manage_leads
      ? [
          {
            key: "campaigns_pending_retry" as const,
            icon: <Mail size={20} />,
            title: "Reenviar campañas",
            subtitle:
              "Campañas con envíos que fallaron y están pendientes de reintento.",
            cta: "Revisar campañas",
            onClick: () => openClientesTab("campanas"),
          },
          {
            key: "urgent_messages" as const,
            icon: <MessageSquare size={20} />,
            title: "Mensajes urgentes",
            subtitle:
              "Quejas o leads con alta urgencia que esperan respuesta.",
            cta: "Ver bandeja",
            onClick: () => openClientesTab("social"),
          },
        ]
      : []),
    {
      key: "low_stock" as const,
      icon: <Package size={20} />,
      title: "Stock bajo",
      subtitle: "Productos que se están agotando y conviene reponer.",
      cta: "Ver productos",
      onClick: () => {
        window.location.hash = "catalogo";
      },
    },
    {
      key: "engine_failures" as const,
      icon: <AlertTriangle size={20} />,
      title: "Envíos fallados",
      subtitle:
        "Mensajes del motor que no pudieron completarse y esperan tu revisión.",
      cta: "Ir a Automatizaciones",
      onClick: () => {
        window.location.hash = "automatizaciones";
      },
    },
  ];

  // Tolerante a esquemas parciales: si el backend (o una respuesta cacheada
  // de antes de un deploy) no trae una tarjeta, se trata como vacía en vez de
  // crashear la pantalla.
  const anythingPending = visibleCards.some(
    (card) => (cards[card.key]?.count ?? 0) > 0,
  );

  return (
    <section id="hoy" className="today" aria-label="Qué necesita tu atención hoy">
      <div className="today-intro">
        <h2>Hoy</h2>
        <p className="muted">
          {anythingPending
            ? "Esto necesita tu atención. Cada tarjeta te lleva directo a resolverlo."
            : "Todo está al día. Vuelve cuando quieras: aquí aparecerá lo que necesite tu atención."}
        </p>
      </div>
      <div className="today-grid">
        {visibleCards.map((card) => (
          <ActionCard
            key={card.key}
            icon={card.icon}
            title={card.title}
            subtitle={card.subtitle}
            count={cards[card.key]?.count ?? 0}
            items={cards[card.key]?.items ?? []}
            cta={card.cta}
            onClick={card.onClick}
            tone={card.key === "low_stock" ? "ok" : "action"}
          />
        ))}
      </div>
      {anythingPending && (
        <p className="today-foot">
          <AlertTriangle size={14} /> Los conteos se actualizan al entrar; si
          acabas de resolver algo, vuelve a esta pantalla.
        </p>
      )}
    </section>
  );
}
