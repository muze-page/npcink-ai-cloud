import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');
const account = read('src/app/admin/accounts/[accountId]/page.tsx');
const site = read('src/app/admin/sites/[siteId]/page.tsx');
const subscription = read('src/app/admin/subscriptions/[subscriptionId]/page.tsx');
const serviceSettings = read('src/app/admin/service-settings/page.tsx');
const modal = read('src/components/ui/Modal.tsx');
const providerDialog = read('src/components/admin/ProviderConnectionDialog.tsx');
const dialogHook = read('src/hooks/useDialogKeyboard.ts');
const runtimeProfiles = read('src/app/admin/runtime-profiles/page.tsx');
const aiResources = read('src/app/admin/ai-resources/page.tsx');
const planDetail = read('src/app/admin/plans/[planId]/page.tsx');
const layout = read('src/app/admin/layout.tsx');

for (const [name, source] of [
  ['customer detail', account],
  ['site detail', site],
  ['subscription detail', subscription],
]) {
  assert.doesNotMatch(source, /window\.location\.reload/, `${name} must retry its bounded read without a full application reload`);
  assert.match(source, /AdminRouteSkeleton/, `${name} must preserve the route shell while loading`);
  assert.match(source, /BackofficeDiagnosticNotice/, `${name} must use the shared error and retry surface`);
}

assert.match(dialogHook, /event\.key === 'Escape'[\s\S]*event\.key !== 'Tab'[\s\S]*previouslyFocused\?\.focus\(\)/, 'custom admin dialogs must share Escape, focus containment, and trigger restoration');
assert.match(runtimeProfiles, /const dialogRef = useDialogKeyboard<[\s\S]*ref=\{dialogRef\}/, 'hosted runtime profile editing must use the shared keyboard behavior');
assert.doesNotMatch(runtimeProfiles, /cloudBindingDialogRef|runtime-binding|embedding/i, 'hosted runtime profiles must not retain the removed Cloud dependency dialog');
assert.doesNotMatch(aiResources, /capabilityAddDialogRef|capabilityAddDialogOpen/, 'model supplier management must not keep the retired capability supplier dialog');
assert.match(planDetail, /editorDialogRef = useDialogKeyboard[\s\S]*ref=\{editorDialogRef\}/, 'package editor must use shared keyboard behavior');
assert.match(serviceSettings, /emailPreviewDialogRef = useDialogKeyboard[\s\S]*ref=\{emailPreviewDialogRef\}/, 'email preview drawer must use shared keyboard behavior');
assert.match(layout, /commandDialogRef = useDialogKeyboard[\s\S]*ref=\{commandDialogRef\}/, 'quick switcher must use shared keyboard behavior');

assert.doesNotMatch(serviceSettings, /window\.confirm/, 'internal unsaved navigation must not use a browser-native confirmation');
assert.match(serviceSettings, /pendingNavigationHref[\s\S]*<ConfirmModal[\s\S]*discard_and_leave/, 'internal unsaved navigation must use the shared confirm modal');

for (const [name, source] of [
  ['shared modal', modal],
  ['provider dialog', providerDialog],
]) {
  assert.match(source, /event\.key === 'Escape'/, `${name} must support Escape`);
  assert.match(source, /event\.key !== 'Tab'/, `${name} must contain keyboard focus`);
  assert.match(source, /document\.body\.style\.overflow = 'hidden'/, `${name} must prevent background scroll`);
  assert.match(source, /previous(?:ActiveElementRef\.current|lyFocused)\?\.focus\(\)/, `${name} must restore focus to its trigger`);
}

console.log('admin_pc_interaction_consistency_contract: ok');
