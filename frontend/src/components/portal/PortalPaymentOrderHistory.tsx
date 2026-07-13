'use client';

import { PortalStatusBadge } from '@/components/portal/PortalStatusBadge';
import {
  type PortalPaymentOrder,
  type PortalPaymentOrderListPayload,
  type PortalPaymentOrderStatusGroup,
} from '@/lib/portal-client';
import {
  DEFAULT_PORTAL_CURRENCY,
  formatPortalCurrency,
  normalizePortalCurrency,
} from '@/lib/currency';
import { formatDate, formatNumber } from '@/lib/utils';

export const PORTAL_PAYMENT_ORDER_PAGE_SIZE = 10;

type TranslateFn = (key: string, params?: Record<string, string>, fallback?: string) => string;

type PortalPaymentOrderHistoryProps = {
  t: TranslateFn;
  payload: PortalPaymentOrderListPayload | null;
  counts: Record<PortalPaymentOrderStatusGroup, number>;
  statusGroup: PortalPaymentOrderStatusGroup;
  offset: number;
  isLoading: boolean;
  error: string | null;
  cancelPendingOrderId: string | null;
  cancelConfirmOrderId: string | null;
  onStatusGroupChange: (statusGroup: PortalPaymentOrderStatusGroup) => void;
  onOffsetChange: (offset: number) => void;
  onCancelConfirmChange: (orderId: string | null) => void;
  onCancel: (order: PortalPaymentOrder) => void;
};

function normalizePaymentText(value: unknown): string {
  return String(value || '').trim().toLowerCase().replace(/[\s_-]+/g, '_');
}

export function isPortalPaymentOrderPending(order: PortalPaymentOrder): boolean {
  return normalizePaymentText(order.status) === 'pending';
}

function resolvePaymentOrderTitle(order: PortalPaymentOrder, t: TranslateFn): string {
  const packId = String(order.credit_pack?.pack_id || '').trim();
  const rawTitle = String(order.credit_pack?.label || order.subject || '').trim();
  const normalized = normalizePaymentText(`${packId} ${rawTitle}`);
  const packKey = normalized.includes('pack_small') || normalized.includes('small_credit_pack')
    ? 'pack_small'
    : normalized.includes('pack_medium') || normalized.includes('medium_credit_pack')
      ? 'pack_medium'
      : normalized.includes('pack_large') || normalized.includes('large_credit_pack')
        ? 'pack_large'
        : '';

  if (packKey) {
    return t(`portal.usage.credit_pack_${packKey}`, {}, rawTitle || order.order_id);
  }
  if (normalizePaymentText(order.purchase_kind).includes('subscription')) {
    const tier = String(order.metadata?.target_tier_id || '').trim();
    const tierLabel = tier ? `${tier.charAt(0).toUpperCase()}${tier.slice(1)}` : '';
    return tierLabel
      ? t(
          'portal.usage.payment_order_subscription_title',
          { tier: tierLabel },
          `${tierLabel} monthly package`
        )
      : rawTitle;
  }
  return rawTitle || order.order_id;
}

function resolvePaymentOrderStatusLabel(order: PortalPaymentOrder, t: TranslateFn): string {
  const status = normalizePaymentText(order.status);
  const code = normalizePaymentText(order.status_detail?.code);
  if (code.includes('expired')) return t('portal.usage.payment_order_status_expired', {}, 'Expired');
  if (code.includes('awaiting_payment_confirmation') || status === 'pending') {
    return t('portal.usage.payment_order_status_waiting_confirmation', {}, 'Waiting for payment confirmation');
  }
  if (code.includes('paid') || status === 'paid') return t('portal.usage.payment_order_status_paid', {}, 'Paid');
  if (code.includes('refund') || status === 'refunded') return t('portal.usage.payment_order_status_refunded', {}, 'Refunded');
  if (status === 'failed') return t('portal.usage.payment_order_status_failed', {}, 'Failed');
  if (status === 'canceled' || status === 'cancelled') {
    return t('portal.usage.payment_order_status_canceled', {}, 'Canceled');
  }
  return t('portal.usage.payment_order_status_unknown', {}, 'To confirm');
}

function resolvePaymentProviderLabel(order: PortalPaymentOrder, t: TranslateFn): string {
  const provider = normalizePaymentText(order.provider);
  if (provider === 'alipay') return t('portal.usage.payment_provider_alipay', {}, 'Alipay');
  if (provider === 'wechat_pay' || provider === 'wechat') {
    return t('portal.usage.payment_provider_wechat', {}, 'WeChat Pay');
  }
  if (provider === 'manual') return t('portal.usage.payment_provider_manual', {}, 'Manual payment');
  return String(order.provider || '').trim() || t('portal.usage.payment_provider_unknown', {}, 'Payment provider');
}

function resolvePaymentOrderDetail(order: PortalPaymentOrder, t: TranslateFn): string {
  const status = normalizePaymentText(order.status);
  const code = normalizePaymentText(order.status_detail?.code);
  if (code.includes('expired')) {
    return t('portal.usage.payment_order_expired_detail', {}, 'This unpaid order has expired.');
  }
  if (code.includes('awaiting_payment_confirmation') || status === 'pending') {
    const provider = resolvePaymentProviderLabel(order, t);
    return t(
      'portal.usage.payment_order_waiting_confirmation_detail',
      { provider },
      `Waiting for ${provider} confirmation. Package changes or credits are granted after provider confirmation.`
    );
  }
  if (code.includes('paid') || status === 'paid') {
    return t('portal.usage.payment_order_paid_detail', {}, 'Payment has been confirmed.');
  }
  if (code.includes('refund') || status === 'refunded') {
    return t('portal.usage.payment_order_refunded_detail', {}, 'This order has been refunded.');
  }
  if (status === 'failed') return t('portal.usage.payment_order_failed_detail', {}, 'Payment was not completed.');
  if (status === 'canceled' || status === 'cancelled') {
    return t('portal.usage.payment_order_canceled_detail', {}, 'This unpaid order was canceled.');
  }
  return t('portal.usage.payment_order_default_detail', {}, 'Payment status is recorded by Cloud.');
}

function paymentOrderAllowsAction(
  order: PortalPaymentOrder,
  action: 'continue_payment' | 'cancel'
): boolean {
  return Array.isArray(order.available_actions) && order.available_actions.includes(action);
}

function formatPaymentOrderReference(orderId: string): string {
  const normalized = String(orderId || '').trim();
  if (normalized.length <= 20) return normalized;
  return `${normalized.slice(0, 14)}...${normalized.slice(-4)}`;
}

export function PortalPaymentOrderHistory({
  t,
  payload,
  counts,
  statusGroup,
  offset,
  isLoading,
  error,
  cancelPendingOrderId,
  cancelConfirmOrderId,
  onStatusGroupChange,
  onOffsetChange,
  onCancelConfirmChange,
  onCancel,
}: PortalPaymentOrderHistoryProps) {
  const orders = payload?.items || [];
  const total = Number(payload?.pagination?.total || 0);
  const pageEnd = Math.min(offset + orders.length, total);
  const tabs: Array<{ id: PortalPaymentOrderStatusGroup; label: string }> = [
    { id: 'all', label: t('portal.usage.payment_orders_tab_all', {}, 'All') },
    { id: 'pending', label: t('portal.usage.payment_orders_tab_pending', {}, 'Pending') },
    { id: 'paid', label: t('portal.usage.payment_orders_tab_paid', {}, 'Paid') },
    { id: 'closed', label: t('portal.usage.payment_orders_tab_closed', {}, 'Closed') },
  ];

  return (
    <details
      className="group overflow-hidden rounded-[18px] border border-slate-200 bg-white shadow-none dark:border-slate-800 dark:bg-slate-950"
      open={Number(counts.pending || 0) > 0}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">
          <span className="block text-sm font-semibold text-gray-950 dark:text-white">
            {t('portal.usage.payment_orders_title', {}, 'Payment orders')}
          </span>
          <span className="mt-1 block text-sm text-gray-600 dark:text-gray-400">
            {Number(counts.all || 0) > 0
              ? t(
                  'portal.usage.payment_orders_summary',
                  {
                    pending: String(counts.pending || 0),
                    paid: String(counts.paid || 0),
                    closed: String(counts.closed || 0),
                  },
                  `${counts.pending || 0} pending, ${counts.paid || 0} paid, ${counts.closed || 0} closed`
                )
              : t('portal.usage.payment_orders_empty', {}, 'No payment orders yet.')}
          </span>
        </span>
        <span aria-hidden="true" className="shrink-0 text-lg text-slate-500 transition-transform group-open:rotate-180">⌄</span>
      </summary>
      <div className="border-t border-slate-200 px-5 pb-5 pt-4 dark:border-slate-800">
        <p className="text-sm text-gray-600 dark:text-gray-400">
          {t(
            'portal.usage.payment_orders_desc',
            {},
            'Payment results follow verified Alipay notifications. Unpaid orders close after 30 minutes; canceled orders remain visible here for 7 days.'
          )}
        </p>
        <div
          role="tablist"
          aria-label={t('portal.usage.payment_orders_filter_label', {}, 'Filter payment orders')}
          className="mt-4 inline-flex max-w-full gap-1 overflow-x-auto rounded-[0.875rem] bg-slate-100 p-1 dark:bg-slate-900"
        >
          {tabs.map((tab) => {
            const selected = tab.id === statusGroup;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={selected}
                className={`min-h-11 whitespace-nowrap rounded-[0.625rem] px-3 py-2 text-sm font-medium transition-colors ${
                  selected
                    ? 'bg-white text-blue-700 shadow-sm dark:bg-slate-800 dark:text-blue-300'
                    : 'text-slate-600 hover:text-slate-950 dark:text-slate-400 dark:hover:text-white'
                }`}
                onClick={() => {
                  onStatusGroupChange(tab.id);
                  onOffsetChange(0);
                  onCancelConfirmChange(null);
                }}
              >
                {tab.label} <span className="tabular-nums">{counts[tab.id] || 0}</span>
              </button>
            );
          })}
        </div>
        {error ? <p className="mt-3 text-sm text-red-700 dark:text-red-300">{error}</p> : null}
        <div className="mt-4" role="tabpanel">
          {isLoading && orders.length === 0 ? (
            <p className="rounded-xl border border-slate-200 px-4 py-6 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
              {t('portal.usage.payment_orders_loading', {}, 'Loading payment orders...')}
            </p>
          ) : orders.length > 0 ? (
            <div className="divide-y divide-slate-200 overflow-hidden rounded-xl border border-slate-200 text-sm dark:divide-slate-800 dark:border-slate-800">
              {orders.map((order) => {
                const isConfirmingCancel = cancelConfirmOrderId === order.order_id;
                const isPending = isPortalPaymentOrderPending(order);
                return (
                  <div
                    key={order.order_id}
                    data-payment-order-id={order.order_id}
                    className="grid gap-3 px-4 py-3 md:grid-cols-[minmax(0,1fr)_auto_auto] md:items-center"
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-semibold text-slate-950 dark:text-white">
                          {resolvePaymentOrderTitle(order, t)}
                        </p>
                        <PortalStatusBadge
                          label={resolvePaymentOrderStatusLabel(order, t)}
                          status={order.status || 'pending'}
                        />
                      </div>
                      {isPending ? (
                        <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                          {resolvePaymentOrderDetail(order, t)}
                        </p>
                      ) : null}
                      {order.purchase_kind === 'credit_pack' && Number(order.credit_pack?.ai_credits || 0) > 0 ? (
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                          {t(
                            'portal.usage.payment_order_credit_snapshot',
                            { credits: formatNumber(Number(order.credit_pack?.ai_credits || 0)) },
                            `${formatNumber(Number(order.credit_pack?.ai_credits || 0))} points in this order`
                          )}
                        </p>
                      ) : null}
                      <p
                        className={`${isPending ? 'mt-2' : 'mt-1'} text-xs font-medium text-slate-500 dark:text-slate-400`}
                        title={order.order_id}
                      >
                        {t(
                          'portal.usage.payment_order_provider_reference',
                          {
                            provider: resolvePaymentProviderLabel(order, t),
                            order: formatPaymentOrderReference(order.order_id),
                          },
                          `${resolvePaymentProviderLabel(order, t)}, order ${formatPaymentOrderReference(order.order_id)}`
                        )}
                      </p>
                    </div>
                    <div className="md:min-w-36 md:text-right">
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        {t('portal.usage.payment_order_purchase_amount', {}, 'Purchase amount')}
                      </p>
                      <p className="font-semibold text-slate-950 dark:text-white">
                        {formatPortalCurrency(Number(order.amount || 0), {
                          from: normalizePortalCurrency(order.currency),
                          to: DEFAULT_PORTAL_CURRENCY,
                        })}
                      </p>
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        {isPending && order.expires_at
                          ? t(
                              'portal.usage.payment_order_expires_at',
                              { time: formatDate(order.expires_at) },
                              `Complete payment before ${formatDate(order.expires_at)}`
                            )
                          : order.created_at ? formatDate(order.created_at) : order.order_id}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 md:min-w-48 md:justify-end">
                      {paymentOrderAllowsAction(order, 'continue_payment') && order.checkout_url ? (
                        <a className="btn btn-primary" href={order.checkout_url} target="_blank" rel="noopener noreferrer">
                          {t('portal.usage.payment_order_continue', {}, 'Continue payment')}
                        </a>
                      ) : null}
                      {paymentOrderAllowsAction(order, 'cancel') ? (
                        isConfirmingCancel ? (
                          <>
                            <button
                              type="button"
                              className="btn btn-danger"
                              disabled={cancelPendingOrderId !== null}
                              onClick={() => onCancel(order)}
                            >
                              {cancelPendingOrderId === order.order_id
                                ? t('common.saving', {}, 'Saving...')
                                : t('portal.usage.payment_order_confirm_cancel', {}, 'Confirm cancel')}
                            </button>
                            <button
                              type="button"
                              className="btn btn-secondary"
                              disabled={cancelPendingOrderId !== null}
                              onClick={() => onCancelConfirmChange(null)}
                            >
                              {t('common.back', {}, 'Back')}
                            </button>
                          </>
                        ) : (
                          <button
                            type="button"
                            className="btn btn-outline text-red-700 dark:text-red-300"
                            disabled={cancelPendingOrderId !== null}
                            onClick={() => onCancelConfirmChange(order.order_id)}
                          >
                            {t('portal.usage.payment_order_cancel', {}, 'Cancel')}
                          </button>
                        )
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="rounded-xl border border-slate-200 px-4 py-6 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
              {t('portal.usage.payment_orders_filter_empty', {}, 'No orders in this status.')}
            </p>
          )}
        </div>
        {total > PORTAL_PAYMENT_ORDER_PAGE_SIZE ? (
          <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {t(
                'portal.usage.payment_orders_page_summary',
                {
                  start: String(total > 0 ? offset + 1 : 0),
                  end: String(pageEnd),
                  total: String(total),
                },
                `${offset + 1}-${pageEnd} of ${total}`
              )}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                className="btn btn-secondary"
                disabled={offset === 0 || isLoading}
                onClick={() => onOffsetChange(Math.max(0, offset - PORTAL_PAYMENT_ORDER_PAGE_SIZE))}
              >
                {t('common.previous', {}, 'Previous')}
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={!payload?.pagination?.has_more || isLoading}
                onClick={() => onOffsetChange(offset + PORTAL_PAYMENT_ORDER_PAGE_SIZE)}
              >
                {t('common.next', {}, 'Next')}
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </details>
  );
}
