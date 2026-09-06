export function calc(x: number): number {
  return x + 1;
}

export interface Priced {
  amount: number;
}

export class Processor {
  run(x: number): number {
    return calc(x);
  }
}
