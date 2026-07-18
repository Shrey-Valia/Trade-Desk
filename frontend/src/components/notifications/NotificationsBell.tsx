import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Modal } from "@/components/ui/Modal";
import {
  useMarkNotificationsRead,
  useNotifications,
} from "@/components/notifications/useNotifications";
import { relativeTime } from "@/components/positions/panelChrome";
import { isPayoutNotification, type Notification } from "@/lib/notificationsApi";

/**
 * Notification-center bell (workstream D3) — account lifecycle notifications
 * (funded / failed / payout decisions / renewals), distinct from the price
 * AlertsBell beside it.
 *
 * Header affordance matching the AlertsBell control styling exactly: a
 * 36×36 tier-2 button, unread-count badge (capped at "9+"), opening a
 * top-aligned panel of the newest notifications with a "Mark all read"
 * action. Clicking an item marks it read; payout-kind items additionally
 * deep-link to /payouts (where the adjudication history explains the
 * decision the notification announced).
 */
export function NotificationsBell() {
  const [open, setOpen] = useState(false);
  const { data } = useNotifications();
  const unread = data?.unread ?? 0;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={`Notifications${unread ? ` (${unread} unread)` : ""}`}
        title="Notifications — account & payout updates"
        className="relative h-9 w-9 flex items-center justify-center bg-tier-2 border border-tier-3 hover:bg-tier-3 rounded-btn text-fg-secondary hover:text-fg-primary"
      >
        {/* Inbox-tray glyph — deliberately NOT the bell shape, so the two
            header affordances (price alerts vs account inbox) read apart. */}
        <svg
          width={18}
          height={18}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.8}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M22 12h-6l-2 3h-4l-2-3H2" />
          <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11" />
        </svg>
        {unread > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full text-[10px] leading-4 text-white text-center bg-amber tabular-nums">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>
      {open && (
        <NotificationsPanel
          items={data?.items ?? []}
          unread={unread}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

function NotificationsPanel({
  items,
  unread,
  onClose,
}: {
  items: Notification[];
  unread: number;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const markRead = useMarkNotificationsRead();

  function handleItemClick(n: Notification) {
    if (n.read_at == null) markRead.mutate([n.id]);
    if (isPayoutNotification(n)) {
      onClose();
      navigate("/payouts");
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      labelledBy="notifications-panel-title"
      align="top"
      panelClassName="w-full max-w-md bg-tier-1 border border-hairline-strong rounded-btn shadow-2xl flex flex-col max-h-[80vh]"
    >
      <div className="flex items-center gap-3 px-4 py-3 border-b border-hairline shrink-0">
        <h2
          id="notifications-panel-title"
          className="text-medium font-medium text-fg-primary"
        >
          Notifications
        </h2>
        {unread > 0 && (
          <span
            className="border border-amber text-amber px-1 uppercase tracking-label-up tabular-nums"
            style={{ fontSize: 11, borderRadius: 2 }}
          >
            {unread} unread
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {unread > 0 && (
            <button
              type="button"
              onClick={() => markRead.mutate(undefined)}
              disabled={markRead.isPending}
              className="text-tiny uppercase tracking-label-up text-fg-tertiary-2 hover:text-fg-primary disabled:opacity-40"
            >
              Mark all read
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="Close notifications"
            className="text-medium leading-none text-fg-secondary hover:text-fg-primary px-1"
          >
            ×
          </button>
        </div>
      </div>
      {items.length === 0 ? (
        <div className="px-4 py-6 text-sm text-fg-tertiary-2 text-center">
          No notifications yet — funding, payout decisions, and renewals show
          up here.
        </div>
      ) : (
        <ul className="overflow-y-auto min-h-0 divide-y divide-hairline">
          {items.map((n) => (
            <NotificationRow key={n.id} item={n} onClick={handleItemClick} />
          ))}
        </ul>
      )}
    </Modal>
  );
}

function NotificationRow({
  item,
  onClick,
}: {
  item: Notification;
  onClick: (n: Notification) => void;
}) {
  const isUnread = item.read_at == null;
  const linksToPayouts = isPayoutNotification(item);
  return (
    <li>
      <button
        type="button"
        onClick={() => onClick(item)}
        title={linksToPayouts ? "Open Payouts" : undefined}
        className="w-full text-left px-4 py-2.5 flex items-start gap-2.5 hover:bg-tier-2 transition-colors duration-75"
      >
        <span
          className={`shrink-0 w-1.5 h-1.5 rounded-full mt-1.5 ${
            isUnread ? "bg-amber" : "bg-tier-3"
          }`}
          aria-hidden
        />
        <span className="flex-1 min-w-0">
          <span className="flex items-baseline gap-2">
            <span
              className={`text-sm truncate ${
                isUnread ? "text-fg-primary font-medium" : "text-fg-secondary"
              }`}
            >
              {item.title}
            </span>
            <span className="ml-auto text-tiny text-fg-tertiary-2 shrink-0 tabular-nums">
              {relativeTime(item.created_at)}
            </span>
          </span>
          {item.body && (
            <span className="block text-xs2 text-fg-tertiary-2 line-clamp-2 mt-0.5">
              {item.body}
            </span>
          )}
        </span>
        {linksToPayouts && (
          <span
            className="text-tiny text-fg-tertiary-2 shrink-0 mt-0.5"
            aria-hidden
          >
            →
          </span>
        )}
      </button>
    </li>
  );
}
