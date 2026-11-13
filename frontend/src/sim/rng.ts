/** Deterministic PRNG (mulberry32). Every stochastic choice in the simulation draws from this. */
export class Rng {
  private s: number
  constructor(seed: number) {
    this.s = seed >>> 0
  }
  next(): number {
    this.s = (this.s + 0x6d2b79f5) >>> 0
    let t = this.s
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
  range(lo: number, hi: number): number {
    return lo + (hi - lo) * this.next()
  }
  get state(): number {
    return this.s
  }
}
