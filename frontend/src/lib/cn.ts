/** Tiny className combiner — joins truthy strings with a space. */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}
