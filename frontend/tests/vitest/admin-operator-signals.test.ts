import { describe, expect, it } from 'vitest';
import { buildAdminOperatorWatchItems } from '@/lib/admin-operator-signals';

function buildInputs(overrides = {}) {
	return {
		runtimeSummary: {
			queuedRuns: 0,
			runningRuns: 0,
			callbackFailed: 0,
			callbackPending: 0,
			guardEvents: 0,
		},
		expiringSubscriptionsIn7Days: 0,
		attentionSubscriptionsCount: 0,
		firstAttentionReason: '',
		hostedModelGovernance: {
			status: 'inactive',
			alertCount: 0,
			firstAlertTitle: '',
			firstAlertSummary: '',
			summary: '',
		},
		formatValue: (value: number) => String(value),
		copy: {
			callbackTitle: 'Callback failures',
			callbackReason: 'Callbacks failed.',
			guardTitle: 'Guard events',
			guardReason: 'Guard events are active.',
			expiryTitle: 'Expiring subscriptions',
			expiryReason: 'Subscriptions are expiring.',
			attentionTitle: 'Coverage attention',
			attentionFallbackReason: 'Coverage needs attention.',
			hostedTitle: 'Runtime telemetry needs review',
			hostedReason: 'Runtime telemetry coverage needs review.',
		},
		...overrides,
	};
}

describe( 'buildAdminOperatorWatchItems', () => {
	it( 'places runtime telemetry errors beside the highest operator risks', () => {
		const items = buildAdminOperatorWatchItems(
			buildInputs( {
				attentionSubscriptionsCount: 1,
				firstAttentionReason: 'Billing follow-up is active.',
				hostedModelGovernance: {
					status: 'error',
					alertCount: 2,
					firstAlertTitle: 'Runtime metering gap',
					firstAlertSummary: 'Image and vector runs are missing metering.',
					summary: 'Runtime telemetry has gaps.',
				},
			} )
		);

		expect( items.map( ( item ) => item.scope ) ).toEqual( [
			'runtime.telemetry_coverage',
			'commercial.subscription',
		] );
		expect( items[0] ).toMatchObject( {
			severity: 'action-needed',
			value: '2',
			title: 'Runtime metering gap',
		} );
	} );

	it( 'keeps runtime telemetry warnings in the main queue ahead of expiry-only work', () => {
		const items = buildAdminOperatorWatchItems(
			buildInputs( {
				expiringSubscriptionsIn7Days: 1,
				hostedModelGovernance: {
					status: 'warning',
					alertCount: 1,
					firstAlertTitle: 'Provider call coverage gap',
					firstAlertSummary: 'Some runtime runs do not have provider telemetry.',
					summary: 'Runtime telemetry has coverage gaps.',
				},
			} )
		);

		expect( items.map( ( item ) => item.scope ) ).toEqual( [
			'runtime.telemetry_coverage',
			'commercial.subscription',
		] );
		expect( items[0] ).toMatchObject( {
			severity: 'warn',
			value: '1',
			reason: 'Some runtime runs do not have provider telemetry.',
		} );
	} );
} );
