/* Controller integration in a simulated DOM. No browser rendering or visual-fidelity claims. */
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),html=fs.readFileSync(path.join(root,'index.html'),'utf8');let checks=0,scroll=0,frameTick=null,audioInstance;
const check=(name,fn)=>{fn();checks++;console.log('PASS '+name);};
class El{constructor(){this.events={};this.attrs={};this.dataset={};this.textContent='';this.disabled=false;this.classes=new Set();this.classList={add:c=>this.classes.add(c),remove:c=>this.classes.delete(c),toggle:(c,b)=>{const v=b??!this.classes.has(c);v?this.classes.add(c):this.classes.delete(c);return v;}};this.style={setProperty:(k,v)=>this.style[k]=v};this.children={};this.rect={width:1280,height:700,top:0};this.open=false;}addEventListener(n,f){this.events[n]=f;}setAttribute(k,v){this.attrs[k]=v;}getAttribute(k){return this.attrs[k]??null;}set src(v){this.attrs.src=v;}get src(){return this.attrs.src;}querySelector(s){return this.children[s]||null;}getBoundingClientRect(){return {...this.rect,top:this.rect.top-scroll};}focus(){this.focused=true;}showModal(){this.open=true;}close(){this.open=false;this.events.close?.();}}
const ids={};for(const m of html.matchAll(/\bid="([^"]+)"/g))ids[m[1]]=new El();
const operations=[];const scenes=['storm','intelligence','people','command','future'].map((id,i)=>{const e=ids[id];e.rect.top=i*700;e.children['.stage']=e;for(const key of ['.routes','.radar','.clouds','.flash'])e.children[key]=new El();if(i!==3){const cv=new El();cv.getContext=()=>({setTransform(){},clearRect(){},beginPath(){},moveTo(x,y){operations.push([x,y]);},lineTo(){},stroke(){},fillRect(x,y){operations.push([x,y]);}});e.children.canvas=cv;}return e;});
const openers=[...html.matchAll(/<button[^>]*class="[^"]*open-dashboard[^"]*"[^>]*>/g)].map(m=>{const e=new El();e.dataset.tab=m[0].match(/data-tab="([^"]+)"/)?.[1];return e;});
const layers=['routes','radar','clouds'].map(key=>{const e=new El();e.dataset.layer=key;e.attrs['aria-pressed']='true';e.children.span=new El();return e;});
const decisions=['RELEASE','REVIEW','HOLD'].map(key=>{const e=new El();e.dataset.decision=key;return e;});
const document={body:new El(),hidden:false,events:{},querySelector:s=>s.startsWith('#')?ids[s.slice(1)]:null,querySelectorAll:s=>({'.scene':scenes,'.open-dashboard':openers,'.layer-toggle':layers,'[data-decision]':decisions}[s]||[]),addEventListener(n,f){this.events[n]=f;}};
class Audio{constructor(){audioInstance=this;this.enabled=false;this.scene=0;}async toggle(){this.enabled=!this.enabled;return this.enabled;}setVolume(v){this.volume=v;}setScene(v){this.scene=v;}click(){}thunder(){this.thunderCalled=true;}duck(v){this.ducked=v;}async visibility(){}dispose(){this.disposed=true;}}
const window={NyayaAudio:Audio,events:{},addEventListener(n,f){this.events[n]=f;}};
const media={matches:false,addEventListener(n,f){this.change=f;}};let observers=[];
class Observer{constructor(cb){this.cb=cb;observers.push(this);}observe(){}disconnect(){}}
const requests=[];const context=vm.createContext({window,document,matchMedia:()=>media,ResizeObserver:Observer,IntersectionObserver:Observer,devicePixelRatio:1,innerHeight:700,performance:{now:()=>0},requestAnimationFrame:f=>(frameTick=f,1),cancelAnimationFrame(){},setTimeout:f=>{f();return 1;},fetch:async url=>{requests.push(url);return{ok:true,json:async()=>JSON.parse(fs.readFileSync(path.join(root,url),'utf8'))};},console});
vm.runInContext(fs.readFileSync(path.join(root,'cinematic.js'),'utf8'),context);
(async()=>{await new Promise(r=>setImmediate(r));
check('Startup does not load dashboard iframe or activate audio',()=>{assert.equal(ids['dashboard-frame'].src,undefined);assert.equal(audioInstance.enabled,false);});
check('Landing loads only recorded evaluation evidence',()=>{assert.deepEqual(requests,['fixtures/simulate.json']);assert.match(ids['evidence-comparison'].textContent,/22.5% → 0.06%/);});
observers[1].cb(scenes.map(el=>({target:el,isIntersecting:true})));frameTick(100);const first=operations.at(-1);frameTick(150);check('Particles move between frames without scrolling',()=>assert.notDeepEqual(operations.at(-1),first));
scroll=1400;frameTick(200);check('Scroll selects scene-specific audio',()=>assert.equal(audioInstance.scene,2));
check('Scrolling sends no banking requests',()=>{assert.equal(requests.length,1);assert.equal(ids['dashboard-frame'].src,undefined);});
await ids.sound.events.click();check('Sound requires click and updates accessible state',()=>{assert.equal(audioInstance.enabled,true);assert.equal(ids.sound.attrs['aria-pressed'],'true');});
await ids.sound.events.click();check('Sound toggles off',()=>assert.equal(audioInstance.enabled,false));
layers[0].events.click();check('Map controls affect visual layer only',()=>{assert.equal(layers[0].attrs['aria-pressed'],'false');assert.ok(scenes[1].children['.routes'].classes.has('layer-off'));assert.equal(requests.length,1);});
decisions[1].events.click();check('Review card shows protocol explanation without API call',()=>{assert.match(ids['decision-detail'].textContent,/stipend/);assert.equal(requests.length,1);});
const policy=openers.find(e=>e.dataset.tab==='tab-policy');policy.events.click();check('Explicit dashboard click loads correct existing tab',()=>{assert.equal(ids['dashboard-frame'].src,'dashboard.html#tab-policy');assert.equal(ids['dashboard-dialog'].open,true);assert.equal(audioInstance.ducked,true);});
let selected=null,paused=false;ids['dashboard-frame'].contentWindow={nyayaDashboardReady:true,switchTab:t=>selected=t,pauseReplay:()=>paused=true};ids['dashboard-frame'].events.load();check('Loaded dashboard receives selected tab',()=>assert.equal(selected,'tab-policy'));
ids['close-dashboard'].events.click();check('Closing dashboard restores focus and pauses replay',()=>{assert.equal(ids['dashboard-dialog'].open,false);assert.equal(audioInstance.ducked,false);assert.equal(policy.focused,true);assert.equal(paused,true);});
ids.motion.events.click();check('Motion pause control updates state',()=>{assert.equal(ids.motion.attrs['aria-pressed'],'true');assert.ok(document.body.classes.has('paused'));});
media.matches=true;media.change();check('System reduced-motion preference is respected',()=>{assert.equal(ids.motion.disabled,true);assert.equal(ids.motion.textContent,'Reduced motion');});
ids.quality.events.change({target:{value:'lite'}});check('Lite quality mode can be selected',()=>assert.ok(document.body.classes.has('lite')));
window.events.pagehide({persisted:false});check('Page cleanup disposes audio',()=>assert.equal(audioInstance.disposed,true));
console.log(`\n${checks} cinematic controller checks passed with simulated DOM. Browser layout, GPU effects and playback are unverified.`);
})().catch(e=>{console.error(e);process.exitCode=1;});
