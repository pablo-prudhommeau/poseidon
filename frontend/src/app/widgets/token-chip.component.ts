import { Component, Input } from '@angular/core';
import { NgIf } from '@angular/common';

@Component({
    standalone: true,
    selector: 'token-chip',
    imports: [NgIf],
    templateUrl: './token-chip.component.html'
})
export class TokenChipComponent {
    @Input() chain: string | undefined;  // peut être undefined : on gère fallback propre
    @Input() address!: string;
    @Input() symbol!: string;

    chainIcon(): string {
        const c = (this.chain || '').toLowerCase();
        if (!c) return 'https://icons.llamao.fi/icons/chains/rsz_unknown.jpg';
        // DeFiLlama: pas besoin de mapping fixe, on tente le slug tel quel
        return `https://icons.llamao.fi/icons/chains/rsz_${c}.jpg`;
    }

    tokenIconUrls(): string[] {
        const c = (this.chain || '').toLowerCase();
        const a = (this.address || '').toLowerCase();
        const list: string[] = [];
        // 1) DexScreener CDN (le plus fréquent)
        if (c && a) list.push(`https://cdn.dexscreener.com/token-icons/${c}/${a}.png`);
        // 2) TrustWallet assets (on évite un énorme mapping; seul 'smartchain' est spécial)
        if (a && c) {
            const folder = (c === 'bsc' || c === 'bnb') ? 'smartchain' : c;
            list.push(`https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/${folder}/assets/${a}/logo.png`);
        }
        // 3) Identicon stable (fallback final)
        if (a) list.push(`https://effigy.im/a/${a}.png`);
        return list;
    }

    onTokenError(ev: Event) {
        const img = ev.target as HTMLImageElement;
        const current = img.getAttribute('data-idx') || '0';
        const next = parseInt(current, 10) + 1;
        const candidates = this.tokenIconUrls();
        if (next < candidates.length) {
            img.src = candidates[next];
            img.setAttribute('data-idx', String(next));
        } else {
            img.style.display = 'none';
        }
    }

    onChainError(ev: Event) {
        const img = ev.target as HTMLImageElement;
        img.src = 'https://icons.llamao.fi/icons/chains/rsz_unknown.jpg';
    }
}
