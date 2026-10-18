/* Web Audio API lifecycle/mixing checks using mock nodes. No claim about audible quality. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
let checks=0;function check(name,fn){fn();checks++;console.log('PASS '+name);}
class Param{constructor(){this.value=0;this.events=[];}setValueAtTime(v,t){this.value=v;this.events.push(['set',v,t]);}setTargetAtTime(v,t,d){this.value=v;this.events.push(['target',v,t,d]);}linearRampToValueAtTime(v,t){this.value=v;this.events.push(['linear',v,t]);}exponentialRampToValueAtTime(v,t){this.value=v;this.events.push(['exp',v,t]);}cancelScheduledValues(t){this.events.push(['cancel',t]);}}
class Node{constructor(){this.gain=new Param();this.frequency=new Param();this.threshold=new Param();this.ratio=new Param();this.connections=[];this.started=false;this.stopped=false;}connect(n){this.connections.push(n);}disconnect(){this.connections=[];}start(t=0){this.started=true;this.startAt=t;}stop(t){this.stopped=true;this.stopAt=t;}}
class Context{constructor(){this.currentTime=10;this.sampleRate=8000;this.destination={};this.state='suspended';this.nodes=[];}node(){const n=new Node();this.nodes.push(n);return n;}createGain(){return this.node();}createDynamicsCompressor(){return this.node();}createBufferSource(){return this.node();}createBiquadFilter(){return this.node();}createOscillator(){return this.node();}createBuffer(_,n){return{getChannelData:()=>new Float32Array(n)};}async resume(){this.state='running';}async suspend(){this.state='suspended';}async close(){this.state='closed';}}
const document={hidden:false},window={AudioContext:Context};let timer=null,cleared=false;
const c=vm.createContext({window,document,Math,setInterval:fn=>(timer=fn,1),clearInterval:()=>cleared=true});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../audio-engine.js'),'utf8'),c);
(async()=>{const audio=new window.NyayaAudio();
check('No audio context or sound before user gesture',()=>{assert.equal(audio.ctx,null);assert.equal(audio.enabled,false);});
await audio.toggle();check('Explicit activation starts context and master at chosen volume',()=>{assert.equal(audio.ctx.state,'running');assert.equal(audio.enabled,true);assert.equal(audio.master.gain.value,.35);});
for(let i=0;i<5;i++){audio.setScene(i);check('Scene '+i+' has one active bus with gradual crossfade',()=>audio.buses.forEach((b,j)=>{assert.equal(b.gain.value,j===i?1:0);assert.equal(b.gain.events.at(-1)[0],'target');assert.equal(b.gain.events.at(-1)[3],.7);}));}
audio.setVolume(.6);audio.duck(true);check('Dashboard attenuates ambience',()=>assert.equal(audio.master.gain.value,.6*.12));audio.duck(false);check('Closing dashboard restores master level',()=>assert.equal(audio.master.gain.value,.6));
audio.setScene(0);audio.thunder();const shot=audio.ctx.nodes.findLast(n=>n.started&&n.stopped);check('Thunder begins after lightning and has bounded lifetime',()=>{assert.equal(shot.startAt,10.45);assert.ok(shot.stopAt<14);});
await audio.toggle();check('Mute zeroes master immediately',()=>{assert.equal(audio.master.gain.value,0);assert.equal(audio.master.gain.events.at(-1)[0],'set');});
const before=audio.ctx.nodes.length;audio.thunder();timer();check('Muted engine schedules no one-shots',()=>assert.equal(audio.ctx.nodes.length,before));
await audio.toggle();document.hidden=true;await audio.visibility();check('Hidden page suspends audio',()=>assert.equal(audio.ctx.state,'suspended'));document.hidden=false;await audio.visibility();check('Visible enabled page resumes audio',()=>assert.equal(audio.ctx.state,'running'));
audio.setVolume(8);check('Volume is clamped to safe control range',()=>assert.equal(audio.volume,1));audio.dispose();check('Disposal stops sources, closes context and clears timer',()=>{assert.equal(audio.ctx.state,'closed');assert.ok(audio.sources.every(s=>s.stopped));assert.equal(cleared,true);});
console.log(`\n${checks} audio lifecycle/mixing checks passed with mocked Web Audio. Listening and browser autoplay behavior require manual verification.`);
})().catch(e=>{console.error(e);process.exitCode=1;});
