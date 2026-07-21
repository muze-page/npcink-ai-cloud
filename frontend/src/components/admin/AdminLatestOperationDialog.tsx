'use client';

import { AdminMutationReceipt, type AdminMutationReceiptPayload } from '@/components/admin/AdminMutationReceipt';
import { Modal } from '@/components/ui/Modal';

type AdminLatestOperationDialogProps = {
  receipt: AdminMutationReceiptPayload | null;
  isOpen: boolean;
  onOpen: () => void;
  onClose: () => void;
  title: string;
  triggerLabel: string;
};

export function AdminLatestOperationButton({
  receipt,
  isOpen,
  onOpen,
  onClose,
  title,
  triggerLabel,
}: AdminLatestOperationDialogProps) {
  if (!receipt) {
    return null;
  }

  return (
    <>
      <button type="button" className="btn btn-secondary btn-sm" onClick={onOpen}>
        {triggerLabel}
      </button>
      <Modal isOpen={isOpen} onClose={onClose} title={title} size="lg">
        <AdminMutationReceipt receipt={receipt} />
      </Modal>
    </>
  );
}
