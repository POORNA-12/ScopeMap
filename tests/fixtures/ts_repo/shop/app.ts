import { calc } from "../pay/core";
import * as core from "../pay/core";

export function checkout(): number {
  return calc(1) + core.calc(2);
}
