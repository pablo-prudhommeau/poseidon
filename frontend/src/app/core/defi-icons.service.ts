// src/app/core/defi-icons.service.ts
import {HttpClient} from '@angular/common/http';
import {Inject, Injectable, LOCALE_ID} from '@angular/core';
import {ICellRendererParams} from 'ag-grid-community';
import {catchError, firstValueFrom, map, of, timeout} from 'rxjs';

/**
 * DefiIconsService
 * ----------------
 * Renders a compact “chip” for DeFi assets (chain + token icon + symbol) inside AG Grid.
 *
 * Goals:
 * - Always show TWO stable circular slots (chain + token) to prevent layout shifts.
 * - Lazy-load images with a fade-in transition.
 * - Resolve the **real token image** via DexScreener API; cache results.
 * - Fall back to DexScreener token-icons then TrustWallet (jsDelivr) if no API image is available.
 * - Provide a robust, dependency-free DOM implementation suitable for AG Grid cellRenderer.
 *
 * Logging:
 * - INFO on first construction.
 * - VERBOSE logs can be toggled with `enableVerboseLogging` if needed during debugging.
 */
@Injectable({providedIn: 'root'})
export class DefiIconsService {
    /** Toggle for very detailed logs (kept false in production). */
    private readonly enableVerboseLogging = false;

    /** Cache of promises resolving the DexScreener CMS image URL per (chain:address:size). */
    private readonly dexImagePromiseCache = new Map<string, Promise<string | null>>();

    /** Cache of already working icon URLs, by logical key (token or chain). */
    private readonly tokenIconCache = new Map<string, string>();
    private readonly chainIconCache = new Map<string, string>();

    constructor(
        @Inject(LOCALE_ID) private readonly localeId: string,
        private readonly http: HttpClient
    ) {
        console.info('poseidon.util.defi-icons — initialized');
    }

    /**
     * AG Grid cellRenderer.
     * Arrow function so `this` stays correctly bound even when AG Grid invokes it as a standalone function.
     */
    public readonly tokenChainChipRenderer = (params: ICellRendererParams): HTMLElement => {
        const row = params.data ?? {};
        const chainName = String(row.chain ?? '').toLowerCase();
        const tokenAddress = String(row.address ?? '').toLowerCase();
        const tokenSymbol = String(row.symbol ?? params.value ?? '').toUpperCase();

        const root = document.createElement('span');
        root.className = 'inline-flex items-center gap-2';

        // CHAIN CIRCLE
        const chainKey = chainName || 'unknown';
        const chainCandidates = this.buildChainIconCandidates(chainKey);
        const chainCircle = this.createIconCircle(chainCandidates, `chain:${chainKey}`, 'chain');

        // TOKEN CIRCLE
        const tokenKey = `${chainName}:${tokenAddress}`;
        const tokenCircle = this.createTokenCircle(chainName, tokenAddress, tokenSymbol, tokenKey);

        // LABEL
        const label = document.createElement('span');
        label.className = 'font-medium';
        label.textContent = tokenSymbol || '—';

        root.appendChild(chainCircle);
        root.appendChild(tokenCircle);
        root.appendChild(label);
        return root;
    };

    // ===================================================================================
    // TOKEN CIRCLE (tries real DexScreener CMS image first, then falls back to CDNs)
    // ===================================================================================

    /**
     * Create the TOKEN icon circle:
     * 1) Resolve the real DexScreener CMS image (cached).
     * 2) If unavailable, try fallbacks: Dex token-icons → TrustWallet.
     * The circle footprint is always 16×16, with a placeholder underneath the image.
     */
    private createTokenCircle(
        chainName: string,
        tokenAddress: string,
        tokenSymbol: string,
        cacheKey: string
    ): HTMLSpanElement {
        const wrapper = this.createFixedCircleWrapper();

        // Placeholder visible until an image loads
        const placeholder = this.createPlaceholder();
        wrapper.appendChild(placeholder);

        // Image (lazy + fade)
        const image = this.createCircleImage('token');
        wrapper.appendChild(image);

        // If a working URL was already cached, apply immediately
        const cachedUrl = this.tokenIconCache.get(cacheKey);
        if (cachedUrl) {
            this.applyImage(image, placeholder, cachedUrl);
            this.logVerbose('token cache hit', {cacheKey, cachedUrl});
            return wrapper;
        }

        // 1) Try the real DexScreener CMS image
        this.resolveDexTokenImageUrl(chainName, tokenAddress, tokenSymbol, 64)
            .then((resolvedUrl) => {
                if (resolvedUrl) {
                    this.applyImage(image, placeholder, resolvedUrl);
                    this.tokenIconCache.set(cacheKey, resolvedUrl);
                    this.logVerbose('dex cms resolved', {cacheKey, resolvedUrl});
                    return;
                }
                // 2) Fallbacks
                this.startTokenFallback(image, placeholder, chainName, tokenAddress, cacheKey);
            })
            .catch((error) => {
                this.logVerbose('dex cms error', {cacheKey, error});
                this.startTokenFallback(image, placeholder, chainName, tokenAddress, cacheKey);
            });

        return wrapper;
    }

    /** Start fallback loading for the token icon. */
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
                    this.applyImage(image, placeholder, image.currentSrc || image.src);
                    this.tokenIconCache.set(cacheKey, image.currentSrc || image.src);
                    this.logVerbose('token fallback success', {cacheKey, url: candidate});
                };
                image.src = candidate;
            } else {
                // No candidate worked: keep the placeholder, hide the <img>
                image.removeAttribute('src');
                image.style.opacity = '0';
                this.logVerbose('token fallback exhausted', {cacheKey});
            }
        };

        tryNext();
    }

    // ===================================================================================
    // DEXSCREENER API (resolve real CMS image)
    // ===================================================================================

    /**
     * Resolve the real DexScreener CMS image URL for a token.
     * Response shape: https://api.dexscreener.com/latest/dex/tokens/{address}
     */
    private resolveDexTokenImageUrl(
        chainName: string,
        tokenAddress: string,
        tokenSymbol: string,
        size = 64
    ): Promise<string | null> {
        if (!chainName || !tokenAddress) {
            return Promise.resolve(null);
        }

        const cacheKey = `${chainName}:${tokenAddress}:${size}`;
        const cachedPromise = this.dexImagePromiseCache.get(cacheKey);
        if (cachedPromise) {
            return cachedPromise;
        }

        const request$ = this.http
            .get<any>(`https://api.dexscreener.com/latest/dex/tokens/${tokenAddress}`)
            .pipe(
                timeout(3500),
                map((res) => this.extractDexImageUrlFromResponse(res)),
                catchError(() => of(null))
            );

        const promise = firstValueFrom(request$).then((url) => {
            if (!url) {
                return null;
            }
            const normalized = this.normalizeExternalImageUrl(url);
            return this.withDexImageParams(normalized, size);
        });

        this.dexImagePromiseCache.set(cacheKey, promise);
        return promise;
    }

    /** Extract a usable image URL from various possible places in DexScreener response. */
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
                pair?.baseToken?.logoURI
            ].filter(Boolean);

            if (directCandidates.length > 0) {
                return String(directCandidates[0]);
            }

            const id = pair?.info?.imageId || pair?.info?.imageHash || pair?.baseToken?.imageId;
            if (id) {
                return `https://cdn.dexscreener.com/cms/images/${id}`;
            }
        }
        return null;
    }

    /** Add CMS query parameters for crisp, square images. */
    private withDexImageParams(url: string, size: number): string {
        // 1) Normaliser d’abord (ipfs/ar/relative)
        const normalized = this.normalizeExternalImageUrl(url);
        try {
            const u = new URL(normalized, 'https://cdn.dexscreener.com');
            // Imgix params
            u.searchParams.set('w', String(size));
            u.searchParams.set('h', String(size));
            u.searchParams.set('fit', 'crop');     // ou 'cover'
            u.searchParams.set('q', '90');         // quality
            u.searchParams.set('fm', 'webp');      // format (PAS "format=auto")
            // Optionnel: densité d’écran
            if (window.devicePixelRatio >= 2) {
                u.searchParams.set('dpr', '2');
            }
            return u.toString();
        } catch {
            const sep = normalized.includes('?') ? '&' : '?';
            return `${normalized}${sep}w=${size}&h=${size}&fit=crop&q=90&fm=webp`;
        }
    }

    // ===================================================================================
    // CHAIN + TOKEN FALLBACK CANDIDATES
    // ===================================================================================

    /** Build the list of token fallback URLs (Dex token-icons → TrustWallet). */
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

    /** DeFiLlama chain icons with safe fallback. */
    private buildChainIconCandidates(chainName: string): string[] {
        return [
            ...(chainName ? [`https://icons.llamao.fi/icons/chains/rsz_${chainName}.jpg`] : []),
            'https://icons.llamao.fi/icons/chains/rsz_unknown.jpg'
        ];
    }

    /** Map Poseidon chain names to TrustWallet folder names. */
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

    // ===================================================================================
    // GENERIC ICON CIRCLE (used for chain icons from a candidates list)
    // ===================================================================================

    /**
     * Create a fixed-size circular icon slot from a list of candidate URLs.
     * Keeps a placeholder under the image to prevent layout shifts.
     * Results are cached per kind (chain / token).
     */
    private createIconCircle(
        srcCandidates: string[],
        cacheKey: string,
        kind: 'chain' | 'token'
    ): HTMLSpanElement {
        const wrapper = this.createFixedCircleWrapper();

        const placeholder = this.createPlaceholder();
        wrapper.appendChild(placeholder);

        const image = this.createCircleImage(kind);
        wrapper.appendChild(image);

        const cache = kind === 'token' ? this.tokenIconCache : this.chainIconCache;
        const cachedUrl = cache.get(cacheKey);
        const orderedCandidates = cachedUrl ? [cachedUrl, ...srcCandidates] : srcCandidates.slice();

        let index = 0;
        const tryNext = () => {
            if (index < orderedCandidates.length) {
                const candidate = orderedCandidates[index++] || '';
                image.onerror = tryNext;
                image.onload = () => {
                    image.classList.add('is-loaded');
                    placeholder.style.opacity = '0';
                    const ok = image.currentSrc || image.src;
                    if (ok) {
                        cache.set(cacheKey, ok);
                    }
                    this.logVerbose(`${kind} candidate success`, {cacheKey, url: ok});
                };
                image.src = candidate;
            } else {
                image.removeAttribute('src');
                image.style.opacity = '0';
                this.logVerbose(`${kind} candidates exhausted`, {cacheKey});
            }
        };

        tryNext();
        return wrapper;
    }

    // ===================================================================================
    // DOM HELPERS (fixed 16×16 circle, lazy + fade)
    // ===================================================================================

    /** Fixed 16×16 wrapper: prevents layout shifts even when images fail or are slow. */
    private createFixedCircleWrapper(): HTMLSpanElement {
        const element = document.createElement('span');
        element.className = 'relative inline-block h-4 w-4 align-middle';
        return element;
    }

    /** Neutral placeholder circle displayed until the image loads. */
    private createPlaceholder(): HTMLSpanElement {
        const element = document.createElement('span');
        element.className = 'absolute inset-0 rounded-full';
        return element;
    }

    /** Image element positioned over the placeholder; uses fade-in CSS. */
    private createCircleImage(alt: 'chain' | 'token'): HTMLImageElement {
        const img = document.createElement('img');
        img.loading = 'lazy';
        img.alt = alt;
        img.width = 16;
        img.height = 16;
        img.className = 'absolute inset-0 h-4 w-4 rounded-full img-fade';
        return img;
    }

    /** Apply a validated image URL and perform the fade-in + placeholder removal. */
    private applyImage(image: HTMLImageElement, placeholder: HTMLElement, url: string): void {
        image.onload = () => {
            image.classList.add('is-loaded'); // relies on .img-fade {opacity:0} + .is-loaded {opacity:1}
            placeholder.style.opacity = '0';
        };
        image.onerror = () => {
            image.style.opacity = '0'; // keep placeholder
        };
        image.src = url;
    }

    // ===================================================================================
    // Logging
    // ===================================================================================

    private logVerbose(message: string, data?: unknown): void {
        if (!this.enableVerboseLogging) {
            return;
        }
        // eslint-disable-next-line no-console
        console.debug(`poseidon.util.defi-icons — ${message}`, data ?? '');
    }

    private normalizeExternalImageUrl(raw: string): string {
        if (!raw) {
            return raw;
        }
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
