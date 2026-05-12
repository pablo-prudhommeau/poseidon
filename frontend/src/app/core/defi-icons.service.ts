import {HttpClient} from '@angular/common/http';
import {inject, Injectable} from '@angular/core';
import {ICellRendererParams} from 'ag-grid-community';
import {catchError, firstValueFrom, map, of, timeout} from 'rxjs';

type IconCategory = 'chain' | 'token' | 'protocol';

interface PersistedIconEntry {
    source: string;
    updatedAt: number;
}

interface DexscreenerPairsResponse {
    pairs: DexscreenerPairPayload[];
}

interface DexscreenerPairPayload {
    info?: DexscreenerPairInfoPayload;
    baseToken?: DexscreenerBaseTokenPayload;
}

interface DexscreenerPairInfoPayload {
    imageUrl?: string;
    headerImage?: string;
    imageId?: string;
    imageHash?: string;
}

interface DexscreenerBaseTokenPayload {
    logo?: string;
    logoUrl?: string;
    image?: string;
    icon?: string;
    logoURI?: string;
    imageId?: string;
}

const ICON_EXTENSIONS: string[] = ['.jpg', '.png'];

const LOCAL_STORAGE_KEY_PREFIX = 'poseidon.iconcache.';
const LOCAL_STORAGE_TTL_MILLISECONDS = 1000 * 60 * 60 * 24 * 7;

const CHAIN_TO_TRUST_WALLET_FOLDER: Record<string, string> = {
    eth: 'ethereum',
    ethereum: 'ethereum',
    bsc: 'smartchain',
    bnb: 'smartchain',
    polygon: 'polygon',
    avax: 'avalanchec',
    avalanche: 'avalanchec',
    arbitrum: 'arbitrum',
    optimism: 'optimism',
    fantom: 'fantom',
    base: 'base',
    sol: 'solana',
    solana: 'solana',
};

const DEXSCREENER_ID_TO_DEFILLAMA_SLUG: Record<string, string> = {
    pumpfun: 'pump.fun',
    'pump-fun': 'pump.fun',
    'raydium-amm': 'raydium',
    'uniswap-v2': 'uniswap',
    'uniswap-v3': 'uniswap',
    'uniswap-v4': 'uniswap',
    'pancakeswap-amm': 'pancakeswap',
    'pancakeswap-amm-v3': 'pancakeswap',
};

@Injectable({providedIn: 'root'})
export class DefiIconsService {
    private readonly httpClient = inject(HttpClient);

    private readonly resolvedIconCache = new Map<string, string>();
    private readonly pendingResolutionCache = new Map<string, Promise<string | null>>();

    constructor() {
        console.info('[UI][ICONS] DefiIconsService initialized');
    }

    public getChainIconCandidates(chainName: string | null | undefined): string[] {
        return this.buildChainIconCandidates(String(chainName ?? '').toLowerCase());
    }

    public getProtocolIconCandidates(dexscreenerId: string | null | undefined): string[] {
        return this.buildProtocolIconCandidates(String(dexscreenerId ?? '').toLowerCase());
    }

    public readonly tokenChainChipRenderer = (params: ICellRendererParams): HTMLElement => {
        const row = params.data ?? {};
        const chainName = String(row.blockchain_network ?? '').toLowerCase();
        const tokenAddress = String(row.token_address ?? '').toLowerCase();
        const tokenSymbol = String(row.token_symbol ?? params.value ?? '').toUpperCase();
        const dexId = String(row.dex_id ?? '').toLowerCase();

        const rootElement = document.createElement('span');
        rootElement.className = 'inline-flex items-center gap-2';

        const chainIconElement = this.buildIconElement(
            this.buildChainIconCandidates(chainName),
            `chain:${chainName || 'unknown'}`,
            'chain',
        );

        let protocolIconElement: HTMLSpanElement | null = null;
        if (dexId && dexId !== 'unknown') {
            protocolIconElement = this.buildIconElement(
                this.buildProtocolIconCandidates(dexId),
                `protocol:${dexId}`,
                'protocol',
            );
        }

        const tokenIconElement = this.buildTokenIconElement(chainName, tokenAddress, tokenSymbol);

        const labelElement = document.createElement('span');
        labelElement.className = 'font-medium';
        labelElement.textContent = tokenSymbol || '—';

        rootElement.appendChild(chainIconElement);
        if (protocolIconElement) {
            rootElement.appendChild(protocolIconElement);
        }
        rootElement.appendChild(tokenIconElement);
        rootElement.appendChild(labelElement);
        return rootElement;
    };

    private buildTokenIconElement(chainName: string, tokenAddress: string, tokenSymbol: string): HTMLSpanElement {
        const cacheKey = `token:${chainName}:${tokenAddress}`;
        const wrapperElement = this.createCircleWrapper();
        const placeholderElement = this.createPlaceholderElement();
        const imageElement = this.createImageElement('token');
        wrapperElement.appendChild(placeholderElement);
        wrapperElement.appendChild(imageElement);

        const persistedSource = this.readFromLocalStorage(cacheKey);
        if (persistedSource) {
            this.applyResolvedImage(imageElement, placeholderElement, persistedSource);
            this.resolvedIconCache.set(cacheKey, persistedSource);
            return wrapperElement;
        }

        const cachedSource = this.resolvedIconCache.get(cacheKey);
        if (cachedSource) {
            this.applyResolvedImage(imageElement, placeholderElement, cachedSource);
            return wrapperElement;
        }

        this.resolveDexscreenerTokenImageUrl(chainName, tokenAddress, tokenSymbol)
            .then((resolvedUrl) => {
                if (resolvedUrl) {
                    this.applyResolvedImage(imageElement, placeholderElement, resolvedUrl);
                    this.resolvedIconCache.set(cacheKey, resolvedUrl);
                    this.writeToLocalStorage(cacheKey, resolvedUrl);
                    this.persistAsDataUrl(cacheKey, resolvedUrl);
                    return;
                }
                this.resolveTokenFallbackCascade(imageElement, placeholderElement, chainName, tokenAddress, cacheKey);
            })
            .catch(() => {
                this.resolveTokenFallbackCascade(imageElement, placeholderElement, chainName, tokenAddress, cacheKey);
            });

        return wrapperElement;
    }

    private resolveTokenFallbackCascade(
        imageElement: HTMLImageElement,
        placeholderElement: HTMLElement,
        chainName: string,
        tokenAddress: string,
        cacheKey: string,
    ): void {
        const fallbackCandidates = this.buildTokenFallbackCandidates(chainName, tokenAddress);
        this.attemptCandidateCascade(imageElement, placeholderElement, fallbackCandidates, cacheKey);
    }

    private resolveDexscreenerTokenImageUrl(chainName: string, tokenAddress: string, tokenSymbol: string): Promise<string | null> {
        if (!chainName || !tokenAddress) {
            return Promise.resolve(null);
        }

        const deduplicationKey = `dex:${chainName}:${tokenAddress}`;
        const pendingPromise = this.pendingResolutionCache.get(deduplicationKey);
        if (pendingPromise) {
            return pendingPromise;
        }

        const resolutionPromise = firstValueFrom(
            this.httpClient
                .get<DexscreenerPairsResponse>(`https://api.dexscreener.com/latest/dex/tokens/${tokenAddress}`)
                .pipe(
                    timeout(3500),
                    map((response) => this.extractImageUrlFromDexscreenerResponse(response)),
                    catchError(() => of(null)),
                ),
        ).then((rawUrl) => {
            if (!rawUrl) {
                return null;
            }
            return this.normalizeExternalImageUrl(rawUrl);
        });

        this.pendingResolutionCache.set(deduplicationKey, resolutionPromise);
        return resolutionPromise;
    }

    private extractImageUrlFromDexscreenerResponse(response: DexscreenerPairsResponse): string | null {
        const pairs = Array.isArray(response?.pairs) ? response.pairs : [];
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
            if (directCandidates.length > 0) {
                return String(directCandidates[0]);
            }
            const imageIdentifier = pair?.info?.imageId || pair?.info?.imageHash || pair?.baseToken?.imageId;
            if (imageIdentifier) {
                return `https://cdn.dexscreener.com/cms/images/${imageIdentifier}`;
            }
        }
        return null;
    }

    private buildTokenFallbackCandidates(chainName: string, tokenAddress: string): string[] {
        const candidates: string[] = [];
        if (!chainName || !tokenAddress) {
            return candidates;
        }
        candidates.push(`https://cdn.dexscreener.com/token-icons/${chainName}/${tokenAddress}.png`);
        const trustWalletFolder = CHAIN_TO_TRUST_WALLET_FOLDER[chainName];
        if (trustWalletFolder) {
            candidates.push(
                `https://cdn.jsdelivr.net/gh/trustwallet/assets@master/blockchains/${trustWalletFolder}/assets/${tokenAddress}/logo.png`,
            );
        }
        return candidates;
    }

    private buildChainIconCandidates(chainName: string): string[] {
        const candidates: string[] = [];
        if (chainName) {
            for (const extension of ICON_EXTENSIONS) {
                candidates.push(`https://icons.llamao.fi/icons/chains/rsz_${chainName}${extension}`);
            }
        }
        candidates.push('https://icons.llamao.fi/icons/chains/rsz_unknown.jpg');
        return candidates;
    }

    private buildProtocolIconCandidates(dexscreenerId: string): string[] {
        if (!dexscreenerId || dexscreenerId === 'unknown') {
            return [];
        }

        const slugVariants = new Set<string>();
        slugVariants.add(dexscreenerId);

        const mappedSlug = DEXSCREENER_ID_TO_DEFILLAMA_SLUG[dexscreenerId];
        if (mappedSlug) {
            slugVariants.add(mappedSlug);
        }

        if (dexscreenerId.endsWith('fun') && !dexscreenerId.endsWith('.fun')) {
            slugVariants.add(dexscreenerId.replace(/fun$/, '.fun'));
        }

        if (dexscreenerId.includes('-')) {
            slugVariants.add(dexscreenerId.split('-')[0]);
        }

        const candidates: string[] = [];
        for (const slug of slugVariants) {
            for (const extension of ICON_EXTENSIONS) {
                candidates.push(`https://icons.llamao.fi/icons/protocols/${slug}${extension}`);
            }
        }
        return candidates;
    }

    private buildIconElement(sourceCandidates: string[], cacheKey: string, category: IconCategory): HTMLSpanElement {
        const wrapperElement = this.createCircleWrapper();
        const placeholderElement = this.createPlaceholderElement();
        const imageElement = this.createImageElement(category);
        wrapperElement.appendChild(placeholderElement);
        wrapperElement.appendChild(imageElement);

        const persistedSource = this.readFromLocalStorage(cacheKey);
        if (persistedSource) {
            this.applyResolvedImage(imageElement, placeholderElement, persistedSource);
            this.resolvedIconCache.set(cacheKey, persistedSource);
            return wrapperElement;
        }

        const cachedSource = this.resolvedIconCache.get(cacheKey);
        if (cachedSource) {
            this.applyResolvedImage(imageElement, placeholderElement, cachedSource);
            return wrapperElement;
        }

        this.attemptCandidateCascade(imageElement, placeholderElement, sourceCandidates, cacheKey);
        return wrapperElement;
    }

    private attemptCandidateCascade(
        imageElement: HTMLImageElement,
        placeholderElement: HTMLElement,
        candidates: string[],
        cacheKey: string,
    ): void {
        let candidateIndex = 0;

        const attemptNextCandidate = (): void => {
            if (candidateIndex >= candidates.length) {
                imageElement.removeAttribute('src');
                imageElement.style.opacity = '0';
                return;
            }
            const candidateUrl = candidates[candidateIndex++];
            imageElement.onerror = attemptNextCandidate;
            imageElement.onload = () => {
                const resolvedSource = imageElement.currentSrc || imageElement.src;
                this.applyResolvedImage(imageElement, placeholderElement, resolvedSource);
                this.resolvedIconCache.set(cacheKey, resolvedSource);
                this.writeToLocalStorage(cacheKey, resolvedSource);
                this.persistAsDataUrl(cacheKey, resolvedSource);
            };
            imageElement.src = candidateUrl;
        };

        attemptNextCandidate();
    }

    private createCircleWrapper(): HTMLSpanElement {
        const element = document.createElement('span');
        element.className = 'relative inline-block h-4 w-4 align-middle';
        return element;
    }

    private createPlaceholderElement(): HTMLSpanElement {
        const element = document.createElement('span');
        element.className = 'absolute inset-0 rounded-full';
        return element;
    }

    private createImageElement(altText: string): HTMLImageElement {
        const element = document.createElement('img');
        element.loading = 'lazy';
        element.alt = altText;
        element.width = 16;
        element.height = 16;
        element.className = 'absolute inset-0 h-4 w-4 rounded-full img-fade';
        return element;
    }

    private applyResolvedImage(imageElement: HTMLImageElement, placeholderElement: HTMLElement, source: string): void {
        imageElement.onload = () => {
            imageElement.classList.add('is-loaded');
            placeholderElement.style.opacity = '0';
        };
        imageElement.onerror = () => {
            imageElement.style.opacity = '0';
        };
        imageElement.src = source;
    }

    private readFromLocalStorage(key: string): string | null {
        try {
            const rawValue = localStorage.getItem(LOCAL_STORAGE_KEY_PREFIX + key);
            if (!rawValue) {
                return null;
            }
            const parsedEntry: PersistedIconEntry = JSON.parse(rawValue);
            const isStillFresh = Date.now() - parsedEntry.updatedAt < LOCAL_STORAGE_TTL_MILLISECONDS;
            return isStillFresh && parsedEntry.source ? parsedEntry.source : null;
        } catch {
            return null;
        }
    }

    private writeToLocalStorage(key: string, source: string): void {
        try {
            const entry: PersistedIconEntry = {source, updatedAt: Date.now()};
            localStorage.setItem(LOCAL_STORAGE_KEY_PREFIX + key, JSON.stringify(entry));
        } catch {
            // localStorage quota exceeded — silently ignored
        }
    }

    private persistAsDataUrl(cacheKey: string, source: string): void {
        fetch(source, {mode: 'cors', credentials: 'omit', cache: 'force-cache'})
            .then((response) => {
                if (!response.ok) {
                    return;
                }
                return response.blob();
            })
            .then((blob) => {
                if (!blob) {
                    return;
                }
                const fileReader = new FileReader();
                fileReader.onloadend = () => {
                    const dataUrl = fileReader.result as string;
                    this.writeToLocalStorage(cacheKey, dataUrl);
                };
                fileReader.readAsDataURL(blob);
            })
            .catch(() => {});
    }

    private normalizeExternalImageUrl(rawUrl: string): string {
        if (!rawUrl) {
            return rawUrl;
        }
        if (rawUrl.startsWith('ipfs://')) {
            const ipfsPath = rawUrl.replace(/^ipfs:\/\//, '').replace(/^ipfs\//, '');
            return `https://cloudflare-ipfs.com/ipfs/${ipfsPath}`;
        }
        if (rawUrl.startsWith('ar://')) {
            const arweaveIdentifier = rawUrl.slice('ar://'.length);
            return `https://arweave.net/${arweaveIdentifier}`;
        }
        if (rawUrl.startsWith('//')) {
            return `https:${rawUrl}`;
        }
        return rawUrl;
    }
}
