import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig( {
	test: {
		environment: 'node',
		include: [ 'tests/vitest/**/*.test.ts', 'tests/vitest/**/*.test.tsx' ],
		exclude: [ '**/node_modules/**', '**/e2e/**' ],
		setupFiles: [ 'tests/vitest/setup.ts' ],
		globals: true,
	},
	resolve: {
		alias: {
			'@': path.resolve( __dirname, './src' ),
		},
	},
} );
