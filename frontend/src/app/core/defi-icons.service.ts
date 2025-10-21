// src/app/core/defi-icons.service.ts
import { HttpClient } from '@angular/common/http';
import { Inject, Injectable, LOCALE_ID } from '@angular/core';
import { ICellRendererParams } from 'ag-grid-community';
import { catchError, firstValueFrom, map, of, timeout } from 'rxjs';

/**
 * DefiIconsService
 * ----------------
 * Renders compact “chips” for DeFi assets (chain + token [+ pair]) inside AG Grid.
 *
 * Triple icon (chain, token, pair) + persistent cache (memory + localStorage TTL).
 *
 * Logging: [UI][ICONS][...]
 */
@Injectable({ providedIn: 'root' })
export class DefiIconsService {
    private readonly enableVerboseLogging = false;

    // localStorage persistence
    private readonly lsPrefix = 'poseidon.iconcache.';
    private readonly lsTtlMs = 1000 * 60 * 60 * 24 * 7; // 7 days

    // Promises cache for Dexscreener image lookups
    private readonly dexImagePromiseCache = new Map<string, Promise<string | null>>();

    // In-memory caches
    private readonly tokenIconCache = new Map<string, string>();
    private readonly chainIconCache = new Map<string, string>();
    private readonly pairIconCache = new Map<string, string>();

    constructor(@Inject(LOCALE_ID) private readonly localeId: string, private readonly http: HttpClient) {
        console.info('[UI][ICONS] DefiIconsService initialized');
    }

    /**
     * AG Grid renderer — chain + token + pair (if available).
     */
    public readonly tokenChainPairChipRenderer = (params: ICellRendererParams): HTMLElement => {
        const row = params.data ?? {};
        const chainName = String(row.chain ?? '').toLowerCase();
        const tokenAddress = String(row.address ?? row.tokenAddress ?? '').toLowerCase();
        const pairAddress = String(row.pairAddress ?? '').toLowerCase();
        const tokenSymbol = String(row.symbol ?? params.value ?? '').toUpperCase();

        const root = document.createElement('span');
        root.className = 'inline-flex items-center gap-2';

        // CHAIN
        const chainKey = chainName || 'unknown';
        const chainCandidates = this.buildChainIconCandidates(chainKey);
        const chainCircle = this.createIconCircle(chainCandidates, `chain:${chainKey}`, 'chain');

        // TOKEN
        const tokenKey = `${chainName}:${tokenAddress}`;
        const tokenCircle = this.createTokenCircle(chainName, tokenAddress, tokenSymbol, tokenKey);

        // PAIR
        const pairCircle =
            pairAddress && chainName
                ? this.createPairCircle(chainName, pairAddress, `pair:${chainName}:${pairAddress}`)
                : this.createFixedCircleWrapper(); // empty footprint to keep layout stable

        const label = document.createElement('span');
        label.className = 'font-medium';
        label.textContent = tokenSymbol || '—';

        root.appendChild(chainCircle);
        root.appendChild(tokenCircle);
        root.appendChild(pairCircle);
        root.appendChild(label);
        return root;
    };

    /**
     * Legacy (2 icons) kept for compat if used ailleurs.
     */
    public readonly tokenChainChipRenderer = (params: ICellRendererParams): HTMLElement => {
        const row = params.data ?? {};
        const chainName = String(row.chain ?? '').toLowerCase();
        const tokenAddress = String(row.address ?? row.tokenAddress ?? '').toLowerCase();
        const tokenSymbol = String(row.symbol ?? params.value ?? '').toUpperCase();

        const root = document.createElement('span');
        root.className = 'inline-flex items-center gap-2';

        const chainKey = chainName || 'unknown';
        const chainCandidates = this.buildChainIconCandidates(chainKey);
        const chainCircle = this.createIconCircle(chainCandidates, `chain:${chainKey}`, 'chain');

        const tokenKey = `${chainName}:${tokenAddress}`;
        const tokenCircle = this.createTokenCircle(chainName, tokenAddress, tokenSymbol, tokenKey);

        const label = document.createElement('span');
        label.className = 'font-medium';
        label.textContent = tokenSymbol || '—';

        root.appendChild(chainCircle);
        root.appendChild(tokenCircle);
        root.appendChild(label);
        return root;
    };

    // =============================================================================
    // TOKEN + PAIR
    // =============================================================================

    private createTokenCircle(chainName: string, tokenAddress: string, tokenSymbol: string, cacheKey: string): HTMLSpanElement {
        const wrapper = this.createFixedCircleWrapper();

        const placeholder = this.createPlaceholder();
        wrapper.appendChild(placeholder);

        const image = this.createCircleImage('token');
        wrapper.appendChild(image);

        // persistent cache
        const persistent = this.getFromLocalStorage(cacheKey);
        if (persistent) {
            this.applyImage(image, placeholder, persistent);
            this.tokenIconCache.set(cacheKey, persistent);
            this.logVerbose('token persistent cache hit', { cacheKey });
            return wrapper;
        }

        // memory cache
        const cachedUrl = this.tokenIconCache.get(cacheKey);
        if (cachedUrl) {
            this.applyImage(image, placeholder, cachedUrl);
            this.logVerbose('token memory cache hit', { cacheKey });
            return wrapper;
        }

        // 1) Dex CMS
        this.resolveDexTokenImageUrl(chainName, tokenAddress, tokenSymbol, 64)
            .then((resolvedUrl) => {
                if (resolvedUrl) {
                    this.applyImage(image, placeholder, resolvedUrl);
                    this.tokenIconCache.set(cacheKey, resolvedUrl);
                    this.persistUrl(cacheKey, resolvedUrl);
                    this.tryPersistAsDataUrl(cacheKey, resolvedUrl).catch(() => {});
                    this.logVerbose('dex cms resolved (token)', { cacheKey, resolvedUrl });
                    return;
                }
                // 2) Fallbacks
                this.startTokenFallback(image, placeholder, chainName, tokenAddress, cacheKey);
            })
            .catch((error) => {
                this.logVerbose('dex cms error (token)', { cacheKey, error });
                this.startTokenFallback(image, placeholder, chainName, tokenAddress, cacheKey);
            });

        return wrapper;
    }

    private createPairCircle(chainName: string, pairAddress: string, cacheKey: string): HTMLSpanElement {
        const wrapper = this.createFixedCircleWrapper();

        const placeholder = this.createPlaceholder();
        wrapper.appendChild(placeholder);

        const image = this.createCircleImage('pair');
        wrapper.appendChild(image);

        // persistent cache
        const persistent = this.getFromLocalStorage(cacheKey);
        if (persistent) {
            this.applyImage(image, placeholder, persistent);
            this.pairIconCache.set(cacheKey, persistent);
            this.logVerbose('pair persistent cache hit', { cacheKey });
            return wrapper;
        }

        // memory cache
        const cachedUrl = this.pairIconCache.get(cacheKey);
        if (cachedUrl) {
            this.applyImage(image, placeholder, cachedUrl);
            this.logVerbose('pair memory cache hit', { cacheKey });
            return wrapper;
        }

        this.resolveDexPairImageUrl(chainName, pairAddress, 64)
            .then((resolvedUrl) => {
                if (resolvedUrl) {
                    this.applyImage(image, placeholder, resolvedUrl);
                    this.pairIconCache.set(cacheKey, resolvedUrl);
                    this.persistUrl(cacheKey, resolvedUrl);
                    this.tryPersistAsDataUrl(cacheKey, resolvedUrl).catch(() => {});
                    this.logVerbose('dex cms resolved (pair)', { cacheKey, resolvedUrl });
                    return;
                }
                image.removeAttribute('src');
                image.style.opacity = '0';
                this.logVerbose('pair image not found; placeholder kept', { cacheKey });
            })
            .catch((error) => {
                this.logVerbose('dex cms error (pair)', { cacheKey, error });
                image.removeAttribute('src');
                image.style.opacity = '0';
            });

        return wrapper;
    }

    private startTokenFallback(
        image: HTMLImageElement,
        placeholder: HTMLElement,
        chainName: string,
        tokenAddress: string,
        cacheKey: string
    ): void {
        const fallbacks = this.buildTokenFallbackCandidates(chainName, tokenAddress);
        let index = 0;

        const tryNext = () => {
            if (index < fallbacks.length) {
                const candidate = fallbacks[index++] || '';
                image.onerror = tryNext;
                image.onload = () => {
                    const ok = image.currentSrc || image.src;
                    this.applyImage(image, placeholder, ok);
                    this.tokenIconCache.set(cacheKey, ok);
                    this.persistUrl(cacheKey, ok);
                    this.tryPersistAsDataUrl(cacheKey, ok).catch(() => {});
                    this.logVerbose('token fallback success', { cacheKey, url: ok });
                };
                image.src = candidate;
            } else {
                image.removeAttribute('src');
                image.style.opacity = '0';
                this.logVerbose('token fallback exhausted', { cacheKey });
            }
        };

        tryNext();
    }

    // =============================================================================
    // Dexscreener API resolvers
    // =============================================================================

    private resolveDexTokenImageUrl(chainName: string, tokenAddress: string, tokenSymbol: string, size = 64): Promise<string | null> {
        if (!chainName || !tokenAddress) return Promise.resolve(null);

        const cacheKey = `token:${chainName}:${tokenAddress}:${size}`;
        const cachedPromise = this.dexImagePromiseCache.get(cacheKey);
        if (cachedPromise) return cachedPromise;

        const request$ = this.http
            .get<any>(`https://api.dexscreener.com/latest/dex/tokens/${tokenAddress}`)
            .pipe(timeout(3500), map((res) => this.extractDexImageUrlFromResponse(res)), catchError(() => of(null)));

        const promise = firstValueFrom(request$).then((url) => {
            if (!url) return null;
            const normalized = this.normalizeExternalImageUrl(url);
            return this.withDexImageParams(normalized, size);
        });

        this.dexImagePromiseCache.set(cacheKey, promise);
        return promise;
    }

    private resolveDexPairImageUrl(chainName: string, pairAddress: string, size = 64): Promise<string | null> {
        if (!chainName || !pairAddress) return Promise.resolve(null);

        const cacheKey = `pair:${chainName}:${pairAddress}:${size}`;
        const cachedPromise = this.dexImagePromiseCache.get(cacheKey);
        if (cachedPromise) return cachedPromise;

        const request$ = this.http
            .get<any>(`https://api.dexscreener.com/latest/dex/pairs/${chainName}/${pairAddress}`)
            .pipe(
                timeout(3500),
                map((res) => {
                    const pair = Array.isArray(res?.pairs) ? res.pairs[0] : res?.pair ?? res;
                    const directCandidates = [
                        pair?.info?.imageUrl,
                        pair?.info?.headerImage,
                        pair?.baseToken?.logo,
                        pair?.baseToken?.logoUrl,
                        pair?.baseToken?.image,
                        pair?.baseToken?.icon,
                        pair?.baseToken?.logoURI,
                    ].filter(Boolean);
                    if (directCandidates.length > 0) return String(directCandidates[0]);
                    const id = pair?.info?.imageId || pair?.info?.imageHash || pair?.baseToken?.imageId;
                    if (id) return `https://cdn.dexscreener.com/cms/images/${id}`;
                    return null;
                }),
                catchError(() => of(null))
            );

        const promise = firstValueFrom(request$).then((url) => {
            if (!url) return null;
            const normalized = this.normalizeExternalImageUrl(url);
            return this.withDexImageParams(normalized, size);
        });

        this.dexImagePromiseCache.set(cacheKey, promise);
        return promise;
    }

    private extractDexImageUrlFromResponse(response: any): string | null {
        const pairs: any[] = Array.isArray(response?.pairs) ? response.pairs : [];
        for (const pair of pairs) {
            const directCandidates = [
                pair?.info?.imageUrl,
                pair?.info?.headerImage,
                pair?.baseToken?.logo,
                pair?.baseToken?.logoUrl,
                pair?.baseToken?.image,
                pair?.baseToken?.icon,
                pair?.baseToken?.logoURI,
            ].filter(Boolean);
            if (directCandidates.length > 0) return String(directCandidates[0]);
            const id = pair?.info?.imageId || pair?.info?.imageHash || pair?.baseToken?.imageId;
            if (id) return `https://cdn.dexscreener.com/cms/images/${id}`;
        }
        return null;
    }

    private withDexImageParams(url: string, size: number): string {
        const normalized = this.normalizeExternalImageUrl(url);
        try {
            const u = new URL(normalized, 'https://cdn.dexscreener.com');
            u.searchParams.set('w', String(size));
            u.searchParams.set('h', String(size));
            u.searchParams.set('fit', 'crop');
            u.searchParams.set('q', '90');
            u.searchParams.set('fm', 'webp');
            if (window.devicePixelRatio >= 2) u.searchParams.set('dpr', '2');
            return u.toString();
        } catch {
            const sep = normalized.includes('?') ? '&' : '?';
            return `${normalized}${sep}w=${size}&h=${size}&fit=crop&q=90&fm=webp`;
        }
    }

    // =============================================================================
    // Candidates + mapping
    // =============================================================================

    private buildTokenFallbackCandidates(chainName: string, tokenAddress: string): string[] {
        const list: string[] = [];
        if (chainName && tokenAddress) {
            list.push(`https://cdn.dexscreener.com/token-icons/${chainName}/${tokenAddress}.png`);
            const trustFolder = this.mapChainToTrustWalletFolder(chainName);
            if (trustFolder) {
                list.push(
                    `https://cdn.jsdelivr.net/gh/trustwallet/assets@master/blockchains/${trustFolder}/assets/${tokenAddress}/logo.png`
                );
            }
        }
        return list;
    }

    private buildChainIconCandidates(chainName: string): string[] {
        return [
            ...(chainName ? [`https://icons.llamao.fi/icons/chains/rsz_${chainName}.jpg`] : []),
            'https://icons.llamao.fi/icons/chains/rsz_unknown.jpg',
        ];
    }

    private mapChainToTrustWalletFolder(chainName: string): string | null {
        switch (chainName) {
            case 'eth':
            case 'ethereum':
                return 'ethereum';
            case 'bsc':
            case 'bnb':
                return 'smartchain';
            case 'polygon':
                return 'polygon';
            case 'avax':
            case 'avalanche':
                return 'avalanchec';
            case 'arbitrum':
                return 'arbitrum';
            case 'optimism':
                return 'optimism';
            case 'fantom':
                return 'fantom';
            case 'base':
                return 'base';
            case 'sol':
            case 'solana':
                return 'solana';
            default:
                return null;
        }
    }

    // =============================================================================
    // Generic circle for a list of candidate URLs (used by CHAIN)
    // =============================================================================

    /**
     * Create a fixed-size circular icon from a list of candidate URLs.
     * Uses memory + localStorage caches. Keeps a placeholder until one candidate loads.
     */
    private createIconCircle(srcCandidates: string[], cacheKey: string, kind: 'chain' | 'token' | 'pair'): HTMLSpanElement {
        const wrapper = this.createFixedCircleWrapper();

        const placeholder = this.createPlaceholder();
        wrapper.appendChild(placeholder);

        const image = this.createCircleImage(kind);
        wrapper.appendChild(image);

        // persistent cache
        const persistent = this.getFromLocalStorage(cacheKey);
        if (persistent) {
            this.applyImage(image, placeholder, persistent);
            this.getCacheForKind(kind).set(cacheKey, persistent);
            this.logVerbose(`${kind} persistent cache hit`, { cacheKey });
            return wrapper;
        }

        // memory cache
        const cache = this.getCacheForKind(kind);
        const cachedUrl = cache.get(cacheKey);
        const ordered = cachedUrl ? [cachedUrl, ...srcCandidates] : srcCandidates.slice();

        let index = 0;
        const tryNext = () => {
            if (index < ordered.length) {
                const candidate = ordered[index++] || '';
                image.onerror = tryNext;
                image.onload = () => {
                    const ok = image.currentSrc || image.src;
                    this.applyImage(image, placeholder, ok);
                    cache.set(cacheKey, ok);
                    this.persistUrl(cacheKey, ok);
                    this.tryPersistAsDataUrl(cacheKey, ok).catch(() => {});
                    this.logVerbose(`${kind} candidate success`, { cacheKey, url: ok });
                };
                image.src = candidate;
            } else {
                image.removeAttribute('src');
                image.style.opacity = '0';
                this.logVerbose(`${kind} candidates exhausted`, { cacheKey });
            }
        };

        tryNext();
        return wrapper;
    }

    private getCacheForKind(kind: 'chain' | 'token' | 'pair'): Map<string, string> {
        if (kind === 'token') return this.tokenIconCache;
        if (kind === 'pair') return this.pairIconCache;
        return this.chainIconCache;
    }

    // =============================================================================
    // DOM helpers
    // =============================================================================

    private createFixedCircleWrapper(): HTMLSpanElement {
        const element = document.createElement('span');
        element.className = 'relative inline-block h-4 w-4 align-middle';
        return element;
    }

    private createPlaceholder(): HTMLSpanElement {
        const element = document.createElement('span');
        element.className = 'absolute inset-0 rounded-full';
        return element;
    }

    private createCircleImage(alt: 'chain' | 'token' | 'pair'): HTMLImageElement {
        const img = document.createElement('img');
        img.loading = 'lazy';
        img.alt = alt;
        img.width = 16;
        img.height = 16;
        img.className = 'absolute inset-0 h-4 w-4 rounded-full img-fade';
        return img;
    }

    private applyImage(image: HTMLImageElement, placeholder: HTMLElement, url: string): void {
        image.onload = () => {
            image.classList.add('is-loaded');
            placeholder.style.opacity = '0';
        };
        image.onerror = () => {
            image.style.opacity = '0';
        };
        image.src = url;
    }

    // =============================================================================
    // Persistence (localStorage)
    // =============================================================================

    private getFromLocalStorage(key: string): string | null {
        try {
            const raw = localStorage.getItem(this.lsPrefix + key);
            if (!raw) return null;
            const stored = JSON.parse(raw) as { src: string; updatedAt: number };
            const fresh = Date.now() - stored.updatedAt < this.lsTtlMs;
            return fresh && stored.src ? stored.src : null;
        } catch {
            return null;
        }
    }

    private persistUrl(key: string, src: string): void {
        try {
            localStorage.setItem(this.lsPrefix + key, JSON.stringify({ src, updatedAt: Date.now() }));
        } catch {
            // ignore quota
        }
    }

    private async tryPersistAsDataUrl(key: string, src: string): Promise<void> {
        try {
            const resp = await fetch(src, { mode: 'cors', credentials: 'omit', cache: 'force-cache' });
            if (!resp.ok) return;
            const blob = await resp.blob();
            const dataUrl = await this.blobToDataUrl(blob);
            this.persistUrl(key, dataUrl);
        } catch {
            // ignore
        }
    }

    private blobToDataUrl(blob: Blob): Promise<string> {
        return new Promise((resolve) => {
            const reader = new FileReader();
            reader.onloadend = () => resolve(reader.result as string);
            reader.readAsDataURL(blob);
        });
    }

    // =============================================================================
    // Logging + normalization
    // =============================================================================

    private logVerbose(message: string, data?: unknown): void {
        if (!this.enableVerboseLogging) return;
        console.debug('[UI][ICONS]', message, data ?? '');
    }

    private normalizeExternalImageUrl(raw: string): string {
        if (!raw) return raw;
        if (raw.startsWith('ipfs://')) {
            const path = raw.replace(/^ipfs:\/\//, '').replace(/^ipfs\//, '');
            return `https://cloudflare-ipfs.com/ipfs/${path}`;
        }
        if (raw.startsWith('ar://')) {
            const id = raw.slice('ar://'.length);
            return `https://arweave.net/${id}`;
        }
        if (raw.startsWith('//')) {
            return `https:${raw}`;
        }
        return raw;
    }
}
