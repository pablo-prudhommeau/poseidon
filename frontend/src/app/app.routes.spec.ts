import { routes } from './app.routes';

describe('app routes', () => {
    it('redirects the empty path to trading', () => {
        const rootRoute = routes.find((route) => route.path === '');

        expect(rootRoute?.redirectTo).toBe('trading');
        expect(rootRoute?.pathMatch).toBe('full');
    });

    it('keeps trading and dca dashboards exposed', () => {
        const routePaths = routes.map((route) => route.path);

        expect(routePaths).toContain('trading');
        expect(routePaths).toContain('dca');
    });
});
