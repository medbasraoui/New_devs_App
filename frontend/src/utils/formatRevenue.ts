export function formatRevenue(amount: string): string {
  if (!/^-?\d+\.\d{2}$/.test(amount)) {
    throw new Error('Invalid revenue amount');
  }
  const [whole, cents] = amount.replace(/^-/, '').split('.');
  const sign = amount.startsWith('-') ? '-' : '';
  const separator = new Intl.NumberFormat().formatToParts(1.1).find(part => part.type === 'decimal')?.value;
  return `${sign}${BigInt(whole).toLocaleString()}${separator}${cents}`;
}
