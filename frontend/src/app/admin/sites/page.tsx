import { redirect } from 'next/navigation';

export default function AdminSitesIndexPage() {
  redirect('/admin/accounts');
}
