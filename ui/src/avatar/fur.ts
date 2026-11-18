// Runtime fur detail for Monkey's furry materials: triplanar strand bumps in the mesh's own (unskinned) space, so
// the strands stick to him as he moves and need no UVs or seams. Only brown fur gets it (faded out on cream skin by
// albedo brightness), plus a little cavity darkening between clumps. Texture: tools/fur/make_fur_detail.py.
import * as THREE from "three";

const uniforms = {
  furTex: { value: null as THREE.Texture | null },
  furScale: { value: 4.8 },          // tiles per metre: one tile ~21 cm, strands 2-5 cm long
  furStrength: { value: 1.0 },       // 0 turns it off (Minimal juice)
};

let loaded = false;
function texture() {
  if (!loaded) {
    loaded = true;
    const t = new THREE.TextureLoader().load("textures/fur_detail.png");
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.colorSpace = THREE.NoColorSpace;
    t.anisotropy = 4;
    uniforms.furTex.value = t;
  }
}

export function setFurStrength(v: number) { uniforms.furStrength.value = v; }

const PARS = /* glsl */ `
uniform sampler2D furTex;
uniform float furScale;
uniform float furStrength;
varying vec3 vFurPos;
varying vec3 vFurNrm;
float furCav; float furMask; vec3 furW; float furHx; float furHy; float furHz;
vec3 furPerturb(vec3 surfPos, vec3 surfNorm, vec2 dHdxy, float faceDir) {
  vec3 sx = normalize(dFdx(surfPos)); vec3 sy = normalize(dFdy(surfPos));
  vec3 r1 = cross(sy, surfNorm); vec3 r2 = cross(surfNorm, sx);
  float det = dot(sx, r1) * faceDir;
  vec3 grad = sign(det) * (dHdxy.x * r1 + dHdxy.y * r2);
  return normalize(abs(det) * surfNorm - grad);
}
void furSample() {
  vec3 w = pow(abs(normalize(vFurNrm)), vec3(4.0)); w /= (w.x + w.y + w.z);
  vec3 p = vFurPos * furScale;
  // strands hang down (texture V = up = +Y in glTF space) on the side/front projections
  vec4 sx = texture2D(furTex, vec2(p.z, p.y * 0.55), 0.8);
  vec4 sz = texture2D(furTex, vec2(p.x, p.y * 0.55), 0.8);
  vec4 sy = texture2D(furTex, p.xz, 0.8);
  furW = w; furHx = sx.r; furHy = sy.r; furHz = sz.r;
  furCav = sx.a * w.x + sy.a * w.y + sz.a * w.z;
}
`;

/** Patch a fur material (MeshPhysicalMaterial) with strand detail. Safe to call once per material. */
export function addFurDetail(mat: THREE.MeshStandardMaterial) {
  texture();
  mat.customProgramCacheKey = () => "monkey-fur-1";
  mat.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, uniforms);
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vFurPos;\nvarying vec3 vFurNrm;")
      .replace("#include <beginnormal_vertex>", "#include <beginnormal_vertex>\nvFurNrm = objectNormal;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nvFurPos = transformed;");
    sh.fragmentShader = sh.fragmentShader
      .replace("#include <common>", "#include <common>\n" + PARS)
      .replace("#include <map_fragment>", `#include <map_fragment>
        furSample();
        float furLum = dot(diffuseColor.rgb, vec3(0.2126, 0.7152, 0.0722));
        furMask = smoothstep(0.22, 0.10, furLum) * furStrength;        // brown fur 1, cream skin 0
        diffuseColor.rgb *= mix(1.0, 0.62 + 0.45 * furCav, 0.55 * furMask);`)
      .replace("#include <normal_fragment_maps>", `#include <normal_fragment_maps>
        float furEdge = 1.0 - clamp(fwidth(furMask) * 14.0, 0.0, 1.0);   // no stipple along fur/skin borders
        float furFacing = smoothstep(0.15, 0.5, abs(dot(normal, normalize(vViewPosition))));  // no shimmer at grazing angles
        // blend each projection's slope (not the slope of the blend, which spikes where projections meet)
        vec2 furD = (vec2(dFdx(furHx), dFdy(furHx)) * furW.x + vec2(dFdx(furHy), dFdy(furHy)) * furW.y
                   + vec2(dFdx(furHz), dFdy(furHz)) * furW.z) * 0.9 * furMask * furEdge * furFacing;
        normal = furPerturb(-vViewPosition, normal, furD, faceDirection);`);
  };
  mat.needsUpdate = true;
}
