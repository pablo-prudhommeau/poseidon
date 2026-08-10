export function formatMiddleEllipsisAddress(rawAddress: string | null | undefined, headCharacterCount: number = 6, tailCharacterCount: number = 4): string {
    if (rawAddress == null || rawAddress === '') {
        return '—';
    }
    const normalizedAddress: string = rawAddress.trim();
    const minimumLengthForEllipsis: number = headCharacterCount + tailCharacterCount + 1;
    if (normalizedAddress.length <= minimumLengthForEllipsis) {
        return normalizedAddress;
    }
    return `${normalizedAddress.slice(0, headCharacterCount)}…${normalizedAddress.slice(-tailCharacterCount)}`;
}
