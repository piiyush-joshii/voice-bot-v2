/** Independent client-side Luhn scan over visible transcript text. */

export function luhnValid(digits: string): boolean {
  if (!/^\d{13,19}$/.test(digits)) return false;
  let total = 0;
  for (let i = 0; i < digits.length; i += 1) {
    let d = Number(digits[digits.length - 1 - i]);
    if (i % 2 === 1) d = d > 4 ? d * 2 - 9 : d * 2;
    total += d;
  }
  return total % 10 === 0;
}

export function countPanLike(text: string): number {
  const compact = text.replace(/[ -]/g, "");
  const re = /\d{13,19}/g;
  let n = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(compact))) {
    if (luhnValid(m[0])) n += 1;
  }
  return n;
}
