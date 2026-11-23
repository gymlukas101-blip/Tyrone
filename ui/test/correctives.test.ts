import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { bendDeg, correctiveWeight, CorrectiveDriver } from "../src/avatar/correctives";

describe("corrective driver", () => {
  it("measures a joint bend and ramps the weight with a smoothstep", () => {
    const a = new THREE.Vector3(0, 1, 0), m = new THREE.Vector3(0, 0, 0);
    expect(bendDeg(a, m, new THREE.Vector3(0, -1, 0))).toBeCloseTo(0, 5);
    expect(bendDeg(a, m, new THREE.Vector3(1, 0, 0))).toBeCloseTo(90, 5);
    expect(correctiveWeight(60, 70, 120)).toBe(0);
    expect(correctiveWeight(95, 70, 120)).toBeCloseTo(0.5, 5);
    expect(correctiveWeight(130, 70, 120)).toBe(1);
  });

  it("drives elbowBend_L from the posed bones and skips models without the morph", () => {
    const root = new THREE.Group();
    const up = new THREE.Bone(); up.name = "upper_armL";
    const fore = new THREE.Bone(); fore.name = "forearmL"; fore.position.set(0, -1, 0);
    const hand = new THREE.Bone(); hand.name = "handL"; hand.position.set(0, -1, 0);
    root.add(up); up.add(fore); fore.add(hand);
    const set: Record<string, number> = {};
    const drv = new CorrectiveDriver(root, (n) => n === "elbowBend_L");
    expect(drv.active).toEqual(["elbowBend_L"]);
    drv.update((n, v) => { set[n] = v; });
    expect(set.elbowBend_L).toBe(0);                       // straight arm
    fore.rotation.z = THREE.MathUtils.degToRad(125);        // bend the elbow
    root.updateMatrixWorld(true);
    drv.update((n, v) => { set[n] = v; });
    expect(set.elbowBend_L).toBe(1);
    expect(new CorrectiveDriver(root, () => false).active).toEqual([]);
  });
});
