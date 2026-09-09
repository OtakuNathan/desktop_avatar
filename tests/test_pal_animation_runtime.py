"""Exercise the real adapter and Three mixer without requiring a GPU."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_pal_clip_selection_transitions_and_completion():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = r'''
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const root = process.argv[1];
const THREE = await import(pathToFileURL(root + '/client/vendor/three.module.min.js'));
let gltf;
class Loader { async loadAsync() { return gltf; } }
const source = fs.readFileSync(root + '/client/js/pal-webgl-avatar.js', 'utf8')
  .replace(/^import .*;\n/gm, '').replace('export async function', 'async function');
const Avatar = new Function('THREE', 'GLTFLoader', 'createPalExpressions', 'createPalSleepParticles', source + '\nreturn PalWebGLAvatar;')(THREE, Loader, () => null, () => null);
async function load(names) {
 const model = new THREE.Group();
 const mesh = new THREE.Mesh(new THREE.BoxGeometry(1, 2, 1), new THREE.MeshBasicMaterial());
 mesh.name = 'body'; model.add(mesh);
 gltf = {scene:model, animations:names.map(name => new THREE.AnimationClip(name, 1, [new THREE.NumberKeyframeTrack('body.rotation[z]', [0,.5,1], [0,.05,0])]))};
 const a = Object.assign(Object.create(Avatar.prototype), {
   state:'standby', destroyed:false, ready:false, clips:new Map(), actions:new Map(),
   modelRoot:new THREE.Group(), modelSize:new THREE.Vector3(),
   widget:{setAttribute(){}},loadingStatus:{remove(){}},resize(){},
   completed:[],onActionFinished(state){this.completed.push(state);},
 });
 await a.load('/fixture.glb'); return a;
}
const a = await load(['Robot_Wave_Pal','Robot_Idle_Pal','Robot_Yes_Pal','Robot_Dance_Pal','curious','sleepy','thinking','working','NlaTrack']);
for (const [state, expected] of [['greeting','Robot_Wave_Pal'],['agree','Robot_Yes_Pal'],['dance','Robot_Dance_Pal'],['confused','curious'],['wink','Robot_Idle_Pal']]) {
 assert.equal(a.setState(state), true, state);
 assert.equal(a.activeAction.getClip().name,expected,state);
}
a.setState('greeting'); a.mixer.update(.4); a.setState('agree'); a.mixer.update(.9);
assert.deepEqual(a.completed,[], 'faded-out greeting must not acknowledge the newer state');
a.mixer.update(.2); assert.deepEqual(a.completed,['agree']);
a.finishAction(); assert.deepEqual(a.completed,['agree'], 'completion is sent once');
a.setState('working'); a.mixer.update(4);
assert.equal(a.activeAction.isRunning(),true); assert.deepEqual(a.completed,['agree']);
a.stopMotion(); assert.equal(a.state,'standby'); assert.equal(a.activeAction.getClip().name,'Robot_Idle_Pal');
a.setState('greeting'); a.mixer.update(.5); a.setState('greeting');
assert.equal(a.activeAction.time,0, 'repeated explicit gestures restart');
a.setState('sleeping'); a.mixer.update(2);
assert.equal(a.activeAction.loop,THREE.LoopOnce);
assert.equal(a.activeAction.paused,true);
assert.equal(a.activeAction.time,1);
a.setState('sleeping'); a.mixer.update(4);
assert.equal(a.activeAction.time,1,'duplicate sleep must hold the final pose');
assert.equal(a.state,'sleeping');
assert.deepEqual(a.completed,['agree'],'sleep must not report expressive completion');
a.setState('standby'); a.mixer.update(.4); a.setState('sleeping');
assert.equal(a.activeAction.time,0,'a new sleep session may settle again');
a.setState('thinking'); a.mixer.update(.4);
const thinkingTime = a.activeAction.time;
a.setState('thinking');
assert.equal(a.activeAction.time,thinkingTime,'duplicate thinking must not restart an active transition');
a.mixer.update(3);
assert.equal(a.activeAction.loop,THREE.LoopOnce);
assert.equal(a.activeAction.paused,true);
assert.equal(a.activeAction.time,1,'thinking must settle instead of looping the leg transition');
a.setState('thinking'); a.mixer.update(3);
assert.equal(a.activeAction.time,1,'duplicate thinking must hold the settled pose');
assert.equal(a.state,'thinking');
assert.deepEqual(a.completed,['agree'],'thinking must not report expressive completion');
a.setState('working'); a.mixer.update(.4); a.setState('thinking');
assert.equal(a.activeAction.time,0,'a new thinking session may settle again');
a.setState('not-a-state');assert.equal(a.state,'standby');
const legacy = await load(['NlaTrack','NlaTrack.001','NlaTrack.002','NlaTrack.003','NlaTrack.004','NlaTrack.005','NlaTrack.006','NlaTrack.007','NlaTrack.008']);
legacy.setState('greeting');assert.equal(legacy.activeAction.getClip().name,'NlaTrack.006');
for (const [state, clip] of [['wink','NlaTrack.006'],['curious','NlaTrack.005'],['sad','NlaTrack.007'],['confused','NlaTrack.003'],['stretching','NlaTrack.008']]) {
 legacy.setState(state); assert.equal(legacy.activeAction.getClip().name,clip,state);
}
legacy.setState('sad'); legacy.mixer.update(2);
assert.deepEqual(legacy.completed,['sad'],'legacy aliases still report their semantic state');
console.log('Pal mixer regression checks passed');
'''
    result = subprocess.run([node, "--input-type=module", "-e", script, str(ROOT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
