import { describe, it, expect } from 'vitest';

describe( 'env contract', () => {
	it( 'should have NODE_ENV defined', () => {
		expect( process.env.NODE_ENV ).toBeDefined();
	} );

	it( 'should resolve @ alias', async () => {
		const mod = await import( '@/app/page' );
		expect( mod ).toBeDefined();
	} );
} );
