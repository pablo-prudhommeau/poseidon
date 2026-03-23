import {Component, Input, OnChanges, SimpleChanges} from '@angular/core';

@Component({
    standalone: true,
    selector: 'token-chip',
    templateUrl: './token-chip.component.html'
})
export class TokenChipComponent implements OnChanges {
    @Input() public blockchain: string | undefined;
    @Input() public contractAddress!: string;
    @Input() public symbol!: string;

    public blockchainIconUrl: string = '';
    public tokenIconCandidates: string[] = [];
    public currentTokenIconIndex: number = 0;
    public isTokenImageVisible: boolean = true;

    private readonly fallbackChainIconUrl = 'https://icons.llamao.fi/icons/chains/rsz_unknown.jpg';

    ngOnChanges(changes: SimpleChanges): void {
        if (changes['blockchain'] || changes['contractAddress']) {
            this.initializeIcons();
        }
    }

    private initializeIcons(): void {
        this.currentTokenIconIndex = 0;
        this.isTokenImageVisible = true;
        this.blockchainIconUrl = this.generateBlockchainIconUrl();
        this.tokenIconCandidates = this.generateTokenIconCandidates();
    }

    private generateBlockchainIconUrl(): string {
        const normalizedBlockchain = (this.blockchain || '').toLowerCase();

        if (!normalizedBlockchain) {
            return this.fallbackChainIconUrl;
        }

        return `https://icons.llamao.fi/icons/chains/rsz_${normalizedBlockchain}.jpg`;
    }

    private generateTokenIconCandidates(): string[] {
        const normalizedBlockchain = (this.blockchain || '').toLowerCase();
        const normalizedAddress = (this.contractAddress || '').toLowerCase();
        const iconCandidates: string[] = [];

        if (normalizedBlockchain && normalizedAddress) {
            iconCandidates.push(`https://cdn.dexscreener.com/token-icons/${normalizedBlockchain}/${normalizedAddress}.png`);
        }

        if (normalizedAddress && normalizedBlockchain) {
            const trustWalletFolder = this.getTrustWalletBlockchainFolder(normalizedBlockchain);
            iconCandidates.push(`https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/${trustWalletFolder}/assets/${normalizedAddress}/logo.png`);
        }

        if (normalizedAddress) {
            iconCandidates.push(`https://effigy.im/a/${normalizedAddress}.png`);
        }

        return iconCandidates;
    }

    private getTrustWalletBlockchainFolder(blockchain: string): string {
        if (blockchain === 'bsc' || blockchain === 'bnb') {
            return 'smartchain';
        }
        return blockchain;
    }

    public handleTokenImageError(): void {
        const nextIndex = this.currentTokenIconIndex + 1;

        if (nextIndex < this.tokenIconCandidates.length) {
            this.currentTokenIconIndex = nextIndex;
        } else {
            this.isTokenImageVisible = false;
        }
    }

    public handleBlockchainImageError(): void {
        this.blockchainIconUrl = this.fallbackChainIconUrl;
    }
}