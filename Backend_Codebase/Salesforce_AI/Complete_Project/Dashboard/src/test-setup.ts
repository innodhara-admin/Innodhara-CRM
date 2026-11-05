/**
 * A real `sessionStorage` for the node test environment.
 *
 * D11 rules out component tests, so there is no jsdom — but the session store
 * and the hand-off both persist through `sessionStorage`, and that is exactly
 * the path worth testing: "the temporary password is never written anywhere
 * readable" is a claim about storage, and asserting it against a store that
 * silently no-ops would prove nothing.
 */
class MemoryStorage implements Storage {
  private map = new Map<string, string>();

  get length(): number {
    return this.map.size;
  }
  clear(): void {
    this.map.clear();
  }
  getItem(key: string): string | null {
    return this.map.get(key) ?? null;
  }
  key(index: number): string | null {
    return [...this.map.keys()][index] ?? null;
  }
  removeItem(key: string): void {
    this.map.delete(key);
  }
  setItem(key: string, value: string): void {
    this.map.set(key, String(value));
  }
}

globalThis.sessionStorage = new MemoryStorage();
